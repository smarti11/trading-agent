"""
Risk Manager
============
Checks stop loss, take profit, daily loss limits, and PDT rules before allowing trades.
"""

import logging
from datetime import datetime, date, timedelta
from pathlib import Path
import pytz
from config.settings import (
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_DAILY_LOSS_USD, MAX_OPEN_POSITIONS,
    PDT_PROTECTION, MAX_DAY_TRADES, MIN_HOLD_HOURS, NO_NEW_TRADES_AFTER, MAX_HOLD_DAYS,
    EMERGENCY_FLOOR_PCT, AGGREGATE_CB_USD,
)
from db.database import (
    get_open_positions, count_active_positions, has_active_symbol,
    get_daily_pnl, get_day_trade_count, was_recently_closed,
)
from core.market_trend import is_trade_allowed, get_market_trend

logger = logging.getLogger("trading_agent")

EASTERN = pytz.timezone("US/Eastern")


class RiskManager:

    def get_eastern_time(self):
        return datetime.now(EASTERN)

    def is_market_open(self) -> bool:
        """Returns True only during regular market hours 9:30am - 4:00pm ET Mon-Fri."""
        now = self.get_eastern_time()
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
        return market_open <= now <= market_close

    def is_too_late_to_trade(self) -> bool:
        """Block new trades after 3:30pm ET to avoid forced same-day closes."""
        now = self.get_eastern_time()
        cutoff_h, cutoff_m = map(int, NO_NEW_TRADES_AFTER.split(":"))
        cutoff = now.replace(hour=cutoff_h, minute=cutoff_m, second=0)
        return now >= cutoff

    def get_rolling_day_trade_count(self) -> int:
        """Count day trades in the last 5 business days."""
        return get_day_trade_count(days=5)

    def can_open_trade(self, symbol: str) -> tuple:
        """Returns (allowed, reason)"""
        # Check circuit breaker
        cb_file = Path(".circuit_breaker")
        if cb_file.exists():
            try:
                triggered_at = datetime.fromisoformat(cb_file.read_text().strip())
                age = (datetime.now() - triggered_at).total_seconds() / 3600
                if age < 24:
                    return False, f"Circuit breaker active (triggered {age:.1f}h ago) — no new trades for 24h"
                else:
                    cb_file.unlink(missing_ok=True)
            except Exception:
                pass

        # Check daily loss limit
        daily_pnl = get_daily_pnl()
        if daily_pnl <= -MAX_DAILY_LOSS_USD:
            return False, f"Daily loss limit hit (${daily_pnl:.2f}). Agent paused."

        # Check max open positions (includes PENDING reservations)
        if count_active_positions() >= MAX_OPEN_POSITIONS:
            return False, f"Max open positions ({MAX_OPEN_POSITIONS}) reached"

        # Check if already in this symbol (OPEN or PENDING)
        if has_active_symbol(symbol):
            return False, f"Already have an active position in {symbol}"

        # PDT check — block new trades after 3:30pm ET
        if PDT_PROTECTION and self.is_too_late_to_trade():
            return False, f"PDT: No new trades after {NO_NEW_TRADES_AFTER} ET (prevents forced same-day close)"

        # Market hours check — don't open positions outside 9:30am-4pm ET
        if not self.is_market_open():
            return False, "Market is closed — no new positions outside 9:30am-4:00pm ET Mon-Fri"

        # Cooldown — don't re-enter a symbol within 24 hours of closing it
        if was_recently_closed(symbol, hours=24):
            return False, f"Cooldown: {symbol} was closed within last 24 hours — skipping to avoid whipsaw"

        # PDT check — rolling 5-day day trade count
        if PDT_PROTECTION:
            dt_count = self.get_rolling_day_trade_count()
            if dt_count >= MAX_DAY_TRADES:
                return False, f"PDT: {dt_count} day trades used in last 5 days (max {MAX_DAY_TRADES}). Holding overnight only."

        return True, "OK"

    def can_open_trade_direction(self, symbol: str, direction: str) -> tuple:
        """
        Full check including market trend filter.
        Call this instead of can_open_trade when direction is known.
        """
        # First run standard checks
        allowed, reason = self.can_open_trade(symbol)
        if not allowed:
            return False, reason

        # Then check market trend
        trend_allowed, trend_reason = is_trade_allowed(direction)
        if not trend_allowed:
            return False, trend_reason

        return True, "OK"

    def can_close_trade(self, symbol: str, entry_ts: str) -> tuple:
        """
        PDT guard: don't close a position same day it was opened
        unless stop loss is hit (emergency exit always allowed).
        """
        if not PDT_PROTECTION:
            return True, "OK"

        try:
            entry_dt = datetime.fromisoformat(entry_ts)
            entry_date = entry_dt.date()
            today = date.today()
            if entry_date == today:
                hours_held = (datetime.now() - entry_dt).seconds / 3600
                if hours_held < MIN_HOLD_HOURS:
                    return False, f"PDT: Position opened today, only held {hours_held:.1f}h (min {MIN_HOLD_HOURS}h). Will close tomorrow."
        except Exception:
            pass
        return True, "OK"

    def get_stop_take(self, action: str, entry_price: float) -> tuple[float, float]:
        """Calculate stop loss and take profit prices."""
        if action == "BUY":
            stop  = round(entry_price * (1 - STOP_LOSS_PCT), 4)
            take  = round(entry_price * (1 + TAKE_PROFIT_PCT), 4)
        else:  # SHORT/SELL
            stop  = round(entry_price * (1 + STOP_LOSS_PCT), 4)
            take  = round(entry_price * (1 - TAKE_PROFIT_PCT), 4)
        return stop, take

    def check_exits(self, current_prices: dict) -> list:
        """
        Given a dict of {symbol: current_price}, check all open positions
        for emergency floor, take profit, or age-based exit triggers.
        Fixed stop-loss removed in v3.0 — use emergency floor (10%) instead.
        Returns list of (symbol, price, reason) tuples.
        """
        to_close = []
        for pos in get_open_positions():
            symbol = pos["symbol"]
            if symbol not in current_prices:
                continue

            price = current_prices[symbol]
            action = pos["action"]
            entry_price = pos["entry_price"]

            entry_date = datetime.fromisoformat(pos["entry_ts"]).date() if pos["entry_ts"] else None
            is_overnight = entry_date and entry_date < date.today()

            # Emergency floor: 10% adverse move — hard exit regardless of PDT
            if action == "BUY":
                loss_pct = (entry_price - price) / entry_price
            else:
                loss_pct = (price - entry_price) / entry_price
            if loss_pct >= EMERGENCY_FLOOR_PCT:
                logger.critical(
                    f"EMERGENCY FLOOR triggered for {symbol} @ ${price} "
                    f"({loss_pct*100:.1f}% loss vs {EMERGENCY_FLOOR_PCT*100:.0f}% floor)"
                )
                to_close.append((symbol, price, "emergency_floor"))
                continue

            # Age-based exit: force close positions held longer than MAX_HOLD_DAYS
            hit_age = False
            age_days = 0
            if entry_date:
                age_days = (date.today() - entry_date).days
                if age_days >= MAX_HOLD_DAYS:
                    hit_age = True

            if hit_age:
                logger.warning(f"AGE EXIT triggered for {symbol} @ ${price} (held {age_days}d, max {MAX_HOLD_DAYS}d)")
                to_close.append((symbol, price, f"age_exit_{age_days}d"))
                continue

            # Take profit
            hit_take = (action == "BUY" and price >= pos["take_profit"]) or \
                       (action != "BUY" and price <= pos["take_profit"])
            if hit_take:
                if is_overnight:
                    logger.info(f"TAKE PROFIT triggered for {symbol} @ ${price} (overnight hold)")
                    to_close.append((symbol, price, "take_profit"))
                else:
                    can_close, reason = self.can_close_trade(symbol, pos["entry_ts"])
                    if can_close:
                        logger.info(f"TAKE PROFIT triggered for {symbol} @ ${price}")
                        to_close.append((symbol, price, "take_profit"))
                    else:
                        logger.info(f"TAKE PROFIT reached for {symbol} but holding: {reason}")

        return to_close

    def check_circuit_breaker(self, open_positions: list, current_prices: dict) -> bool:
        """
        Sum unrealized P&L across all open positions.
        If total loss exceeds AGGREGATE_CB_USD, write .circuit_breaker timestamp
        and return True. Returns False if not triggered.
        """
        total_unrealized = 0.0
        for pos in open_positions:
            sym = pos["symbol"]
            if sym not in current_prices:
                continue
            price = current_prices[sym]
            if pos["action"] == "BUY":
                unreal = (price - pos["entry_price"]) * pos["quantity"]
            else:
                unreal = (pos["entry_price"] - price) * pos["quantity"]
            total_unrealized += unreal

        if total_unrealized <= -AGGREGATE_CB_USD:
            cb_file = Path(".circuit_breaker")
            if not cb_file.exists():
                cb_file.write_text(datetime.now().isoformat())
                logger.critical(
                    f"CIRCUIT BREAKER triggered: aggregate unrealized P&L ${total_unrealized:.2f} "
                    f"(threshold -${AGGREGATE_CB_USD:.0f}). No new trades for 24h."
                )
            return True
        return False
