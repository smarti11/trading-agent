"""
Options Trading Agent — Main Orchestrator
===========================================
v0.2 trend-dip: BULL-only long calls on dip-and-reclaim.

  python options_agent.py                 → paper trading (default)
  python options_agent.py --live          → live trading (USE WITH CAUTION)
  python options_agent.py --once          → single scan, then exit
  python options_agent.py --summary       → print trade summary and exit
  python options_agent.py --force-close   → close all open option positions now

Paper mode is enforced by config/settings.py — PAPER_TRADING must be
explicitly set to False AND --live flag passed to enable live trading.
"""

import argparse
import logging
import sys
import time
from datetime import date as date_cls, datetime
from pathlib import Path

from config.settings import PAPER_TRADING
from config.options_settings import (
  OPTIONS_SCAN_INTERVAL_SEC, OPTIONS_PAPER_TRADING, OPTIONS_LOG_PATH,
  OPTIONS_TRADE_AMOUNT_USD, MAX_RISK_USD, MAX_CONTRACTS,
)
from data.fetcher import get_most_active, get_symbol_data
from data.corporate_events import is_safe_to_trade
from data.options_fetcher import find_tradeable_contract, get_open_position_premiums
from core.options.chain import OptionsContract
from core.options.signals import evaluate_options
from core.options.risk import OptionsRiskManager
from core.market_trend import get_market_trend
from broker.options_orders import OptionsBroker
from db.options_database import (
  init_options_db, log_options_signal, log_options_trade,
  open_option_position_pending, confirm_option_position,
  fail_pending_option_position, close_option_position,
  get_open_option_positions, print_options_summary,
  stamp_options_strategy_version,
)

CURRENT_VERSION = "options_v0.2_trend_dip"

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [%(levelname)s] %(message)s",
  handlers=[
    logging.StreamHandler(),
    logging.FileHandler(OPTIONS_LOG_PATH, mode="a"),
  ],
)
logger = logging.getLogger("options_agent")


def _monitor_open_positions(client: OptionsBroker, risk: OptionsRiskManager, mode: str):
  open_pos = get_open_option_positions()
  if not open_pos:
    return

  premiums = get_open_position_premiums(open_pos)
  for pos in open_pos:
    key = pos["contract_symbol"]
    prem = premiums.get(key)
    logger.info(
      f"Option check: {key} | {pos['option_type']} "
      f"entry=${pos['entry_premium']} stop=${pos['stop_loss']} "
      f"TP=${pos['take_profit']} current=${prem}"
    )

  risk.check_circuit_breaker(open_pos, premiums)

  pos_by_key = {p["contract_symbol"]: p for p in open_pos}
  exits = risk.check_exits(premiums)
  for contract_symbol, premium, reason in exits:
    pos = pos_by_key.get(contract_symbol)
    if not pos:
      continue
    _exit_position(client, pos, premium, reason, mode)


def _exit_position(
    client: OptionsBroker,
    pos,
    premium: float,
    reason: str,
    mode: str,
) -> bool:
  """Place SELL_CLOSE and record exit. Returns True on success."""
  contract_symbol = pos["contract_symbol"]
  contract = OptionsContract(
    underlying=pos["underlying"],
    option_type=pos["option_type"],
    strike=float(pos["strike"]),
    expiration=date_cls.fromisoformat(pos["expiration"]),
    bid=0, ask=0, last=premium, volume=0, open_interest=0,
    implied_volatility=0, in_the_money=False,
    contract_symbol=contract_symbol,
  )
  contracts = pos["contracts"]
  logger.info(
    f"Exiting {contract_symbol} @ ${premium} ({reason}) — "
    f"SELL_CLOSE {contracts} contracts"
  )
  try:
    client.place_option_order(contract, contracts, opening=False)
    close_option_position(contract_symbol, premium)
    log_options_trade(
      contract_symbol, pos["underlying"], pos["option_type"],
      pos["strike"], pos["expiration"], "SELL_CLOSE", contracts,
      premium, mode, "FILLED", notes=reason, strategy_version=CURRENT_VERSION,
    )
    logger.info(f"  ✓ Closed {contract_symbol}")
    return True
  except Exception as e:
    logger.error(f"Exit order failed for {contract_symbol}: {e}")
    return False


def force_close_all_positions(client: OptionsBroker, mode: str) -> int:
  """Force-close every OPEN option position at current premium mark."""
  open_pos = get_open_option_positions()
  if not open_pos:
    print("No open option positions to close.")
    return 0

  premiums = get_open_position_premiums(open_pos)
  closed = 0
  for pos in open_pos:
    key = pos["contract_symbol"]
    premium = premiums.get(key) or float(pos["entry_premium"])
    entry = float(pos["entry_premium"])
    contracts = int(pos["contracts"])
    pnl = (premium - entry) * contracts * 100
    print(
      f"Force-closing {key}: {contracts}x {pos['option_type']} "
      f"entry=${entry:.2f} → exit=${premium:.2f}  P&L ${pnl:+.2f}"
    )
    if _exit_position(client, pos, premium, "force_close", mode):
      closed += 1

  # Clear circuit breaker so new entries can resume after flat book
  cb = Path(".options_circuit_breaker")
  if cb.exists():
    cb.unlink(missing_ok=True)
    logger.info("Cleared options circuit breaker after force-close")
    print("Cleared .options_circuit_breaker")

  print(f"\nForce-closed {closed}/{len(open_pos)} position(s).")
  return closed


def _scan_for_signals(client: OptionsBroker, risk: OptionsRiskManager, mode: str) -> int:
  trend_data = get_market_trend()
  current_trend = trend_data.get("trend", "CHOP")
  symbols = get_most_active()
  logger.info(f"Options scan: {len(symbols)} symbols")
  orders_placed = 0

  for symbol in symbols:
    sym_data = get_symbol_data(symbol)
    if sym_data is None:
      continue

    safe, corp_reason = is_safe_to_trade(symbol)
    if not safe:
      logger.info(f"{symbol}: Skipped — {corp_reason}")
      continue

    signal = evaluate_options(symbol, sym_data.closes, market_trend=current_trend)
    signal_id = log_options_signal(signal)
    if signal.direction == "NONE":
      continue

    option_label = "CALL" if signal.direction == "BUY" else "PUT"
    logger.info(f"OPTIONS SIGNAL [{option_label}] {symbol} | {signal.reason}")

    allowed, risk_reason = risk.can_open_trade(symbol)
    if not allowed:
      logger.info(f"  ↳ Skipped: {risk_reason}")
      continue

    contract, select_reason = find_tradeable_contract(symbol, signal.direction)
    if contract is None:
      logger.info(f"  ↳ No contract: {select_reason}")
      continue

    premium = contract.mid
    if premium <= 0:
      logger.info(f"  ↳ No valid premium for {contract.contract_symbol}")
      continue

    contracts = client.calculate_contracts(premium)
    if contracts < 1:
      logger.warning(
        f"  ↳ {contract.contract_symbol} skipped — premium ${premium:.2f} "
        f"fails risk sizing (max risk ${MAX_RISK_USD}, max {MAX_CONTRACTS} contracts)"
      )
      continue

    stop, take = risk.premium_stops(premium)
    exp_str = contract.expiration.isoformat()

    open_option_position_pending(
      contract.contract_symbol, contract.underlying, contract.option_type,
      contract.strike, exp_str, contracts, premium, stop, take,
    )
    try:
      client.place_option_order(contract, contracts, opening=True)
      confirm_option_position(contract.contract_symbol)
      log_options_trade(
        contract.contract_symbol, contract.underlying, contract.option_type,
        contract.strike, exp_str, "BUY_OPEN", contracts, premium,
        mode, "FILLED" if not OPTIONS_PAPER_TRADING else "PAPER",
        signal_id=signal_id, strategy_version=CURRENT_VERSION,
      )
      logger.info(
        f"  ↳ {'[PAPER] ' if OPTIONS_PAPER_TRADING else ''}"
        f"Opened {contracts}x {contract.contract_symbol} @ ${premium} "
        f"| stop=${stop} TP=${take} DTE={contract.dte}"
      )
      orders_placed += 1
    except Exception as e:
      fail_pending_option_position(contract.contract_symbol)
      logger.error(f"  ↳ Order failed for {contract.contract_symbol}: {e}")
      log_options_trade(
        contract.contract_symbol, contract.underlying, contract.option_type,
        contract.strike, exp_str, "BUY_OPEN", contracts, premium,
        mode, "FAILED", notes=str(e), signal_id=signal_id,
        strategy_version=CURRENT_VERSION,
      )

  return orders_placed


def run_scan(client: OptionsBroker, risk: OptionsRiskManager, mode: str):
  logger.info(
    f"--- Options scan [{mode}] [{CURRENT_VERSION}] "
    f"{datetime.now().strftime('%H:%M:%S')} ---"
  )

  _monitor_open_positions(client, risk, mode)

  if not risk.is_market_open():
    logger.info("Market closed — skipping new options scan")
    logger.info("--- Options scan complete (position check only). ---\n")
    return

  orders = _scan_for_signals(client, risk, mode)
  logger.info(f"--- Options scan complete. {orders} orders placed. ---\n")


def main():
  parser = argparse.ArgumentParser(description="Options Trading Agent")
  parser.add_argument("--live", action="store_true",
                      help="Enable live trading (requires PAPER_TRADING=False)")
  parser.add_argument("--once", action="store_true", help="Run one scan then exit")
  parser.add_argument("--summary", action="store_true", help="Print summary and exit")
  parser.add_argument(
    "--force-close", action="store_true",
    help="Force-close all open option positions at current premium, then exit",
  )
  args = parser.parse_args()

  if args.summary:
    init_options_db()
    print_options_summary()
    return

  if args.live and PAPER_TRADING:
    print("\n⚠️  ERROR: --live passed but PAPER_TRADING=True in config/settings.py")
    print("Set PAPER_TRADING = False AND pass --live to enable live trading.\n")
    sys.exit(1)

  mode = "LIVE" if (args.live and not PAPER_TRADING) else "PAPER"

  if args.force_close:
    init_options_db()
    open_pos = get_open_option_positions()
    if not open_pos:
      print("No open option positions.")
      return
    print(f"\nForce-closing {len(open_pos)} open option position(s) [{mode}]...")
    for p in open_pos:
      print(
        f"  • {p['contract_symbol']}  {p['option_type']}  "
        f"{p['contracts']}x @ ${float(p['entry_premium']):.2f}"
      )
    prompt = (
      "\n⚠️  LIVE force-close. Type YES to continue: "
      if mode == "LIVE"
      else "\nType YES to force-close these paper positions: "
    )
    confirm = input(prompt)
    if confirm.strip().upper() != "YES":
      print("Aborted.")
      sys.exit(0)

    client = OptionsBroker()
    try:
      client.authenticate()
      client.get_account_id()
    except Exception as e:
      logger.error(f"E*Trade auth failed: {e}")
      sys.exit(1)
    force_close_all_positions(client, mode)
    print_options_summary()
    return

  print(f"\n{'='*60}")
  print(f"  OPTIONS TRADING AGENT STARTING")
  print(f"  Mode: {mode}")
  print(f"  Strategy: v0.2 trend-dip (BULL calls only)")
  print(f"  Max risk/trade: ${MAX_RISK_USD} · max {MAX_CONTRACTS} contracts")
  print(f"  Budget cap: ${OPTIONS_TRADE_AMOUNT_USD}")
  print(f"  Scan interval: {OPTIONS_SCAN_INTERVAL_SEC}s")
  print(f"  Press Ctrl+C to stop")
  print(f"{'='*60}\n")

  if mode == "LIVE":
    confirm = input(
      "⚠️  You are about to trade OPTIONS with REAL MONEY. Type 'YES' to continue: "
    )
    if confirm.strip() != "YES":
      print("Aborted.")
      sys.exit(0)

  init_options_db()
  stamp_options_strategy_version(
    CURRENT_VERSION,
    "BULL-only dip-and-reclaim long calls; risk-based size; -35%/+70% exits",
  )
  risk = OptionsRiskManager()
  client = OptionsBroker()

  auth_attempts = 0
  auth_max = 1 if args.once else 12
  while True:
    try:
      client.authenticate()
      client.get_account_id()
      break
    except Exception as e:
      auth_attempts += 1
      logger.error(f"E*Trade auth failed ({auth_attempts}/{auth_max}): {e}")
      if auth_attempts >= auth_max:
        logger.critical("Auth failed — exiting")
        sys.exit(1)
      logger.info("Retrying auth in 60 seconds...")
      time.sleep(60)

  if args.once:
    run_scan(client, risk, mode)
    print_options_summary()
  else:
    while True:
      try:
        run_scan(client, risk, mode)
        if risk.is_after_market_close():
          logger.info("Market session ended — exiting for the day (start me again next session)")
          print_options_summary()
          break
        logger.info(f"Sleeping {OPTIONS_SCAN_INTERVAL_SEC}s until next scan...")
        time.sleep(OPTIONS_SCAN_INTERVAL_SEC)
      except KeyboardInterrupt:
        logger.info("Options agent stopped by user")
        print_options_summary()
        break
      except Exception as e:
        logger.error(f"Unhandled error in scan loop: {e}", exc_info=True)
        time.sleep(30)


if __name__ == "__main__":
  main()
