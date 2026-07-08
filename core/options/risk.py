"""
Options Risk Manager
====================
Premium-based exits, DTE management, and position limits.
"""

import logging
from datetime import datetime, date, timedelta
from pathlib import Path

import pytz

from config.options_settings import (
  MAX_OPTIONS_POSITIONS, MAX_DAILY_LOSS_USD, NO_NEW_TRADES_AFTER,
  STOP_LOSS_PREMIUM_PCT, TAKE_PROFIT_PREMIUM_PCT, FORCE_CLOSE_DTE,
  MAX_HOLD_DAYS, EMERGENCY_FLOOR_PREMIUM_PCT, AGGREGATE_CB_USD,
)
from db.options_database import (
  get_open_option_positions, count_active_option_positions,
  has_active_underlying, get_options_daily_pnl, was_underlying_recently_closed,
)

logger = logging.getLogger("options_agent")
EASTERN = pytz.timezone("US/Eastern")


class OptionsRiskManager:

  def get_eastern_time(self):
    return datetime.now(EASTERN)

  def is_market_open(self) -> bool:
    now = self.get_eastern_time()
    if now.weekday() >= 5:
      return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close

  def is_too_late_to_trade(self) -> bool:
    now = self.get_eastern_time()
    cutoff_h, cutoff_m = map(int, NO_NEW_TRADES_AFTER.split(":"))
    cutoff = now.replace(hour=cutoff_h, minute=cutoff_m, second=0)
    return now >= cutoff

  def can_open_trade(self, underlying: str) -> tuple[bool, str]:
    cb_file = Path(".options_circuit_breaker")
    if cb_file.exists():
      try:
        triggered_at = datetime.fromisoformat(cb_file.read_text().strip())
        age = (datetime.now() - triggered_at).total_seconds() / 3600
        if age < 24:
          return False, f"Options circuit breaker active ({age:.1f}h ago)"
        cb_file.unlink(missing_ok=True)
      except Exception:
        pass

    daily_pnl = get_options_daily_pnl()
    if daily_pnl <= -MAX_DAILY_LOSS_USD:
      return False, f"Daily options loss limit hit (${daily_pnl:.2f})"

    if count_active_option_positions() >= MAX_OPTIONS_POSITIONS:
      return False, f"Max options positions ({MAX_OPTIONS_POSITIONS}) reached"

    if has_active_underlying(underlying):
      return False, f"Already have an active option on {underlying}"

    if self.is_too_late_to_trade():
      return False, f"No new options after {NO_NEW_TRADES_AFTER} ET"

    if not self.is_market_open():
      return False, "Market closed"

    if was_underlying_recently_closed(underlying, hours=24):
      return False, f"Cooldown: {underlying} closed within 24h"

    return True, "OK"

  def premium_stops(self, entry_premium: float) -> tuple[float, float]:
    stop = round(entry_premium * (1 - STOP_LOSS_PREMIUM_PCT), 4)
    take = round(entry_premium * (1 + TAKE_PROFIT_PREMIUM_PCT), 4)
    return max(stop, 0.01), take

  def check_exits(self, current_premiums: dict[str, float]) -> list[tuple[str, float, str]]:
    to_close = []
    today = date.today()

    for pos in get_open_option_positions():
      key = pos["contract_symbol"]
      premium = current_premiums.get(key)
      if premium is None:
        continue

      entry = pos["entry_premium"]
      if entry <= 0:
        continue

      loss_pct = (entry - premium) / entry
      gain_pct = (premium - entry) / entry

      exp = date.fromisoformat(pos["expiration"])
      dte = (exp - today).days
      if dte <= FORCE_CLOSE_DTE:
        to_close.append((key, premium, f"force_close_dte_{dte}"))
        continue

      entry_date = datetime.fromisoformat(pos["entry_ts"]).date() if pos["entry_ts"] else None
      if entry_date and (today - entry_date).days >= MAX_HOLD_DAYS:
        to_close.append((key, premium, f"age_exit_{(today - entry_date).days}d"))
        continue

      if loss_pct >= EMERGENCY_FLOOR_PREMIUM_PCT:
        to_close.append((key, premium, "emergency_floor"))
        continue

      if premium <= pos["stop_loss"]:
        to_close.append((key, premium, "stop_loss"))
        continue

      if premium >= pos["take_profit"]:
        to_close.append((key, premium, "take_profit"))
        continue

      if gain_pct >= TAKE_PROFIT_PREMIUM_PCT:
        to_close.append((key, premium, "take_profit"))

    return to_close

  def check_circuit_breaker(self, open_positions: list, current_premiums: dict[str, float]) -> bool:
    total_unrealized = 0.0
    for pos in open_positions:
      key = pos["contract_symbol"]
      premium = current_premiums.get(key)
      if premium is None:
        continue
      contracts = pos["contracts"]
      entry = pos["entry_premium"]
      total_unrealized += (premium - entry) * contracts * 100

    if total_unrealized <= -AGGREGATE_CB_USD:
      cb_file = Path(".options_circuit_breaker")
      if not cb_file.exists():
        cb_file.write_text(datetime.now().isoformat())
        logger.critical(
          f"OPTIONS CIRCUIT BREAKER: unrealized P&L ${total_unrealized:.2f} "
          f"(threshold -${AGGREGATE_CB_USD:.0f})"
        )
      return True
    return False
