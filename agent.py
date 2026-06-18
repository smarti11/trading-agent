"""
Trading Agent — Main Orchestrator
==================================
Run this file to start the agent.

  python agent.py              → paper trading (default)
  python agent.py --live       → live trading (USE WITH CAUTION)
  python agent.py --once       → single scan, then exit
  python agent.py --summary    → print trade summary and exit

Paper mode is enforced by config/settings.py — PAPER_TRADING must be
explicitly set to False AND --live flag passed to enable live trading.
This double-gate prevents accidental live execution.
"""

import argparse
import logging
import time
import sys
from datetime import datetime

from config.settings import (
    PAPER_TRADING, SCAN_INTERVAL_SEC, TRADE_AMOUNT_USD,
    ALLOW_SHORTS, USE_ATR_STOPS,
)
from data.fetcher import get_most_active, get_symbol_data, get_current_price
from core.atr import atr_filter, overextension_check, get_atr_stops
from core.market_trend import get_market_trend
from data.corporate_events import is_safe_to_trade
from core.signals import evaluate
from core.risk import RiskManager
from broker.etrade import ETradeClient
from db.database import (
    init_db, log_signal, log_trade,
    open_position_pending, confirm_position, fail_pending_position,
    close_position, get_open_positions, print_summary,
    stamp_strategy_version,
)

CURRENT_VERSION = "v3.1_atomic_stops"

_preopen_checked_date = None
_pending_gap_closes: set = set()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/agent.log", mode="a")
    ]
)
logger = logging.getLogger("trading_agent")


def _compute_stops(action: str, entry_price: float, atr_val: float, risk: RiskManager) -> tuple[float, float]:
    """Prefer ATR-based stops when enabled and ATR is available."""
    if USE_ATR_STOPS and atr_val > 0:
        return get_atr_stops(action, entry_price, atr_val)
    return risk.get_stop_take(action, entry_price)


def _monitor_open_positions(client: ETradeClient, risk: RiskManager, mode: str):
    """Check exits, gap closes, and circuit breaker for open positions."""
    global _pending_gap_closes

    open_pos = get_open_positions()
    if not open_pos:
        return

    et_now = risk.get_eastern_time()
    pos_by_symbol = {p["symbol"]: p for p in open_pos}
    current_prices = {}
    for pos in open_pos:
        p = get_current_price(pos["symbol"])
        if p:
            current_prices[pos["symbol"]] = p
        logger.info(
            f"Position check: {pos['symbol']} | action={pos['action']} "
            f"entry=${pos['entry_price']} ref_stop=${pos['stop_loss']} "
            f"TP=${pos['take_profit']} current=${p}"
        )

    risk.check_circuit_breaker(open_pos, current_prices)

    if _pending_gap_closes and et_now.hour >= 9 and et_now.minute >= 30:
        for sym in list(_pending_gap_closes):
            pos = pos_by_symbol.get(sym)
            if not pos:
                _pending_gap_closes.discard(sym)
                continue
            price = current_prices.get(sym)
            if not price:
                continue
            exit_action = "SELL" if pos["action"] == "BUY" else "BUY"
            qty = pos["quantity"]
            logger.info(f"Gap-close executing: {sym} @ ${price} — {exit_action} {qty} shares")
            try:
                client.place_order(sym, exit_action, qty)
                close_position(sym, price)
                log_trade(sym, exit_action, qty, price, mode, "FILLED",
                          notes="gap_close_preopen", strategy_version=CURRENT_VERSION)
                _pending_gap_closes.discard(sym)
                logger.info(f"  ✓ Gap-closed {sym}")
            except Exception as e:
                logger.error(f"Gap-close order failed for {sym}: {e}")

    exits = risk.check_exits(current_prices)
    for symbol, price, reason in exits:
        pos = pos_by_symbol.get(symbol)
        if not pos:
            continue
        exit_action = "SELL" if pos["action"] == "BUY" else "BUY"
        qty = pos["quantity"]
        logger.info(f"Exiting {symbol} @ ${price} ({reason}) — {exit_action} {qty} shares")
        try:
            client.place_order(symbol, exit_action, qty)
            close_position(symbol, price)
            log_trade(symbol, exit_action, qty, price, mode, "FILLED",
                      notes=reason, strategy_version=CURRENT_VERSION)
            logger.info(f"  ✓ Closed {symbol} successfully")
        except Exception as e:
            logger.error(f"Exit order failed for {symbol}: {e}")


def _scan_for_signals(client: ETradeClient, risk: RiskManager, mode: str) -> int:
    """Scan the universe for new entry signals. Returns orders placed."""
    trend_data = get_market_trend()
    current_trend = trend_data.get("trend", "CHOP")
    symbols = get_most_active()
    logger.info(f"Scanning {len(symbols)} symbols: {symbols[:10]}...")
    action_count = 0

    for symbol in symbols:
        sym_data = get_symbol_data(symbol)
        if sym_data is None:
            continue

        prices = sym_data.closes
        ohlc = sym_data.ohlc

        safe, corp_reason = is_safe_to_trade(symbol)
        if not safe:
            logger.info(f"{symbol}: Skipped — {corp_reason}")
            continue

        signal = evaluate(symbol, prices, market_trend=current_trend)
        if signal.direction == "NONE":
            continue

        if signal.direction == "SELL" and not ALLOW_SHORTS:
            logger.info(f"{symbol}: Skipped — SELL signal but ALLOW_SHORTS=False")
            continue

        atr_val = 0.0
        if ohlc is not None and len(ohlc) >= 14:
            tradeable, atr_reason, atr_val, atr_pct = atr_filter(
                symbol, ohlc["Close"], ohlc["High"], ohlc["Low"],
                direction=signal.direction, market_trend=current_trend,
            )
            if not tradeable:
                logger.info(f"{symbol}: Skipped — {atr_reason}")
                continue

            overextended, ext_reason = overextension_check(
                symbol, ohlc["Close"], ohlc["High"], ohlc["Low"]
            )
            if overextended:
                logger.info(f"{symbol}: Skipped — {ext_reason}")
                continue

        signal_id = log_signal(signal)
        logger.info(f"SIGNAL [{signal.direction}] {symbol} | {signal.reason}")

        allowed, risk_reason = risk.can_open_trade_direction(symbol, signal.direction)
        if not allowed:
            logger.info(f"  ↳ Skipped: {risk_reason}")
            continue

        current_price = sym_data.current_price or signal.close_price
        shares = client.calculate_shares(current_price)
        if shares < 1:
            logger.warning(
                f"  ↳ {symbol} skipped — price ${current_price} exceeds "
                f"${TRADE_AMOUNT_USD} per trade limit"
            )
            continue

        stop, take = _compute_stops(signal.direction, current_price, atr_val, risk)

        open_position_pending(symbol, signal.direction, shares, current_price, stop, take)
        try:
            client.place_order(symbol, signal.direction, shares)
            confirm_position(symbol)
            log_trade(
                symbol, signal.direction, shares, current_price,
                mode, "FILLED" if not PAPER_TRADING else "PAPER",
                signal_id=signal_id, strategy_version=CURRENT_VERSION
            )
            logger.info(
                f"  ↳ {'[PAPER] ' if PAPER_TRADING else ''}Order placed: "
                f"{signal.direction} {shares} {symbol} @ ${current_price} "
                f"| ref_stop=${stop} TP=${take}"
            )
            action_count += 1
        except Exception as e:
            fail_pending_position(symbol)
            logger.error(f"  ↳ Order failed for {symbol}: {e}")
            log_trade(symbol, signal.direction, shares, current_price,
                      mode, "FAILED", notes=str(e), signal_id=signal_id,
                      strategy_version=CURRENT_VERSION)

    return action_count


def run_scan(client: ETradeClient, risk: RiskManager, mode: str):
    """One full scan cycle."""
    global _preopen_checked_date, _pending_gap_closes
    logger.info(f"--- Scan started [{mode}] [{CURRENT_VERSION}] {datetime.now().strftime('%H:%M:%S')} ---")

    et_now = risk.get_eastern_time()
    market_open = risk.is_market_open()

    # Pre-open window: 9:10–9:29 ET — scan for gap risk, queue closes
    if et_now.hour == 9 and 10 <= et_now.minute < 30:
        today = et_now.date()
        if _preopen_checked_date != today:
            _preopen_checked_date = today
            from core.preopen import check_preopen_gaps
            open_pos_for_gap = get_open_positions()
            if open_pos_for_gap:
                gaps = check_preopen_gaps(open_pos_for_gap)
                for sym, pre_px, gap_pct in gaps:
                    _pending_gap_closes.add(sym)
                    logger.warning(
                        f"Gap-close queued: {sym} ({gap_pct*100:+.1f}%) — will close at open"
                    )

    _monitor_open_positions(client, risk, mode)

    if not market_open:
        logger.info("Market closed — skipping new signal scan")
        logger.info("--- Scan complete (position check only). ---\n")
        return

    action_count = _scan_for_signals(client, risk, mode)
    logger.info(f"--- Scan complete. {action_count} orders placed. ---\n")


def main():
    parser = argparse.ArgumentParser(description="Mean Reversion Trading Agent")
    parser.add_argument("--live",    action="store_true", help="Enable live trading (requires PAPER_TRADING=False in settings)")
    parser.add_argument("--once",    action="store_true", help="Run one scan then exit")
    parser.add_argument("--summary", action="store_true", help="Print summary and exit")
    args = parser.parse_args()

    if args.summary:
        init_db()
        print_summary()
        return

    if args.live and PAPER_TRADING:
        print("\n⚠️  ERROR: --live flag passed but PAPER_TRADING=True in config/settings.py")
        print("Set PAPER_TRADING = False in config/settings.py AND pass --live to enable live trading.\n")
        sys.exit(1)

    mode = "LIVE" if (args.live and not PAPER_TRADING) else "PAPER"

    print(f"\n{'='*60}")
    print(f"  TRADING AGENT STARTING")
    print(f"  Mode: {mode}")
    print(f"  Scan interval: {SCAN_INTERVAL_SEC}s")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*60}\n")

    if mode == "LIVE":
        confirm = input("⚠️  You are about to trade with REAL MONEY. Type 'YES' to continue: ")
        if confirm.strip() != "YES":
            print("Aborted.")
            sys.exit(0)

    init_db()
    stamp_strategy_version(
        CURRENT_VERSION,
        "Atomic PENDING positions, unified data fetch, ATR stops, market-hours scan gating"
    )
    risk = RiskManager()
    client = ETradeClient()

    auth_attempts = 0
    auth_max_attempts = 1 if args.once else 12
    while True:
        try:
            client.authenticate()
            client.get_account_id()
            break
        except Exception as e:
            auth_attempts += 1
            logger.error(
                f"E*Trade auth failed (attempt {auth_attempts}"
                f"/{auth_max_attempts}): {e}"
            )
            if auth_attempts >= auth_max_attempts:
                logger.critical("Auth failed too many times — exiting")
                sys.exit(1)
            logger.info("Retrying auth in 60 seconds...")
            time.sleep(60)

    if args.once:
        run_scan(client, risk, mode)
        print_summary()
    else:
        while True:
            try:
                run_scan(client, risk, mode)
                logger.info(f"Sleeping {SCAN_INTERVAL_SEC}s until next scan...")
                time.sleep(SCAN_INTERVAL_SEC)
            except KeyboardInterrupt:
                logger.info("Agent stopped by user")
                print_summary()
                break
            except Exception as e:
                logger.error(f"Unhandled error in scan loop: {e}", exc_info=True)
                time.sleep(30)


if __name__ == "__main__":
    main()
