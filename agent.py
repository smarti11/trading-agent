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

from config.settings import PAPER_TRADING, SCAN_INTERVAL_SEC, TRADE_AMOUNT_USD
from data.fetcher import get_most_active, get_price_history, get_current_price, get_ohlc_history
from core.atr import atr_filter, overextension_check
from core.market_trend import get_market_trend
from data.corporate_events import is_safe_to_trade
from core.signals import evaluate
from core.risk import RiskManager
from broker.etrade import ETradeClient
from db.database import (
    init_db, log_signal, log_trade,
    open_position, close_position,
    get_open_positions, print_summary,
    stamp_strategy_version,
)

CURRENT_VERSION = "v3.0_no_stop"

_preopen_checked_date = None
_pending_gap_closes: set = set()

# ------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/agent.log", mode="a")
    ]
)
logger = logging.getLogger("trading_agent")


def run_scan(client: ETradeClient, risk: RiskManager, mode: str):
    """One full scan cycle."""
    global _preopen_checked_date, _pending_gap_closes
    logger.info(f"--- Scan started [{mode}] [{CURRENT_VERSION}] {datetime.now().strftime('%H:%M:%S')} ---")

    et_now = risk.get_eastern_time()

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
                    logger.warning(f"Gap-close queued: {sym} ({gap_pct*100:+.1f}%) — will close at open")

    symbols = get_most_active()
    logger.info(f"Scanning {len(symbols)} symbols: {symbols[:10]}...")

    # --- Check exits on open positions ---
    open_pos = get_open_positions()
    if open_pos:
        pos_by_symbol = {p["symbol"]: p for p in open_pos}
        current_prices = {}
        for pos in open_pos:
            p = get_current_price(pos["symbol"])
            if p:
                current_prices[pos["symbol"]] = p
            logger.info(f"Position check: {pos['symbol']} | action={pos['action']} entry=${pos['entry_price']} ref_stop=${pos['stop_loss']} TP=${pos['take_profit']} current=${p}")

        # Aggregate circuit breaker check
        risk.check_circuit_breaker(open_pos, current_prices)

        # Flush gap-close queue at/after market open
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

    # --- Scan for new signals ---
    # Get current market trend for this scan cycle
    trend_data = get_market_trend()
    current_trend = trend_data.get("trend", "CHOP")

    action_count = 0
    for symbol in symbols:
        prices = get_price_history(symbol)
        if prices is None:
            continue

        # Corporate events check — skip acquired/delisted/pinned symbols
        safe, corp_reason = is_safe_to_trade(symbol)
        if not safe:
            logger.info(f"{symbol}: Skipped — {corp_reason}")
            continue

        # ATR volatility filter — skip symbols that are too volatile or too thin
        ohlc = get_ohlc_history(symbol)
        if ohlc is not None and len(ohlc) >= 14:
            tradeable, atr_reason, atr_val, atr_pct = atr_filter(
                symbol, ohlc["Close"], ohlc["High"], ohlc["Low"],
                direction=None, market_trend=current_trend
            )
            if not tradeable:
                # If blocked by ATR, check if a BUY signal in BULL market
                # would pass with the looser cap
                if current_trend == "BULL":
                    tradeable_bull, _, _, _ = atr_filter(
                        symbol, ohlc["Close"], ohlc["High"], ohlc["Low"],
                        direction="BUY", market_trend="BULL"
                    )
                    if tradeable_bull:
                        # Allow through — will only trade if BUY signal fires
                        logger.info(f"{symbol}: ATR={atr_pct:.1f}% — allowed under BULL+BUY relaxed cap")
                    else:
                        logger.info(f"{symbol}: Skipped — {atr_reason}")
                        continue
                else:
                    logger.info(f"{symbol}: Skipped — {atr_reason}")
                    continue

            # Overextension check — skip news-driven moves > 3x ATR
            overextended, ext_reason = overextension_check(
                symbol, ohlc["Close"], ohlc["High"], ohlc["Low"]
            )
            if overextended:
                logger.info(f"{symbol}: Skipped — {ext_reason}")
                continue
        
        signal = evaluate(symbol, prices, market_trend=current_trend)

        # Log all actionable signals
        if signal.direction != "NONE":
            signal_id = log_signal(signal)
            logger.info(f"SIGNAL [{signal.direction}] {symbol} | {signal.reason}")

            # Risk check including market trend filter
            allowed, risk_reason = risk.can_open_trade_direction(symbol, signal.direction)
            if not allowed:
                logger.info(f"  ↳ Skipped: {risk_reason}")
                continue

            # Size the order
            current_price = get_current_price(symbol) or signal.close_price
            shares = client.calculate_shares(current_price)
            if shares < 1:
                logger.warning(f"  ↳ {symbol} skipped — price ${current_price} exceeds ${TRADE_AMOUNT_USD} per trade limit")
                continue

            stop, take = risk.get_stop_take(signal.direction, current_price)

            # Place order
            try:
                result = client.place_order(symbol, signal.direction, shares)
                open_position(symbol, signal.direction, shares, current_price, stop, take)
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
                logger.error(f"  ↳ Order failed for {symbol}: {e}")
                log_trade(symbol, signal.direction, shares, current_price,
                          mode, "FAILED", notes=str(e), signal_id=signal_id,
                          strategy_version=CURRENT_VERSION)

    logger.info(f"--- Scan complete. {action_count} orders placed. ---\n")


def main():
    parser = argparse.ArgumentParser(description="Mean Reversion Trading Agent")
    parser.add_argument("--live",    action="store_true", help="Enable live trading (requires PAPER_TRADING=False in settings)")
    parser.add_argument("--once",    action="store_true", help="Run one scan then exit")
    parser.add_argument("--summary", action="store_true", help="Print summary and exit")
    args = parser.parse_args()

    # Summary shortcut
    if args.summary:
        init_db()
        print_summary()
        return

    # Double-gate for live trading
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

    # Initialize
    init_db()
    stamp_strategy_version(
        CURRENT_VERSION,
        "Removed 3% fixed stop; added 10% emergency floor, preopen gap-close, aggregate circuit breaker"
    )
    risk = RiskManager()
    client = ETradeClient()

    # Authenticate with retry. If the OAuth verifier isn't available yet
    # (e.g. running under nohup and the user hasn't dropped the code into
    # config/.etrade_verifier yet), we retry instead of crashing the agent.
    # --once exits after the first failure; the persistent loop keeps trying.
    auth_attempts = 0
    auth_max_attempts = 1 if args.once else 12  # ~6 hours under nohup
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

    # Run loop
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
                time.sleep(30)  # brief pause before retrying


if __name__ == "__main__":
    main()
