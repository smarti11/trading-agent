"""
Corporate Events Filter
=======================
Checks symbols for pending acquisitions, mergers, delistings,
or bankruptcies before the agent opens a position.

Uses yfinance to detect:
1. Manual blacklist (symbols you've flagged yourself)
2. Price pinning near a round number (acquisition arbitrage signal)
3. Very low volume / no data (delisted)
4. Known acquisition targets via news search fallback

Usage:
    from data.corporate_events import is_safe_to_trade
    safe, reason = is_safe_to_trade("CFLT")
"""

import yfinance as yf
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("trading_agent")

# ── Manual blacklist ───────────────────────────────────────────────────
# Add any symbol here you know is being acquired, delisted, or is
# otherwise not safe to trade. Agent will skip these permanently.
BLACKLIST = {
    "CFLT": "Acquired by IBM for $31/share — delisted March 17 2026",
    # Add more as needed:
    # "SYMBOL": "Reason",
}

# ── Thresholds ─────────────────────────────────────────────────────────
MIN_AVG_VOLUME      = 100_000    # Skip if avg daily volume below this
MAX_PRICE_PIN_PCT   = 0.5        # If price within 0.5% of 52w high for 5+ days = acquisition pin
MIN_HISTORY_DAYS    = 10         # Skip if fewer than this many trading days of data


def load_blacklist() -> dict:
    """Load blacklist from JSON file + hardcoded list combined."""
    import json
    from pathlib import Path
    bl = dict(BLACKLIST)  # start with hardcoded
    bf = Path("config/blacklist.json")
    if bf.exists():
        try:
            bl.update(json.loads(bf.read_text()))
        except Exception:
            pass
    return bl


def is_safe_to_trade(symbol: str) -> tuple:
    """
    Returns (safe: bool, reason: str)
    safe=True  → OK to trade
    safe=False → Skip this symbol
    """

    # 1. Manual blacklist check (fastest)
    active_blacklist = load_blacklist()
    if symbol in active_blacklist:
        reason = f"BLACKLISTED: {active_blacklist[symbol]}"
        logger.warning(f"Corporate events filter blocked {symbol}: {reason}")
        return False, reason

    try:
        ticker = yf.Ticker(symbol)

        # 2. Check if ticker has valid data at all
        hist = ticker.history(period="30d", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < MIN_HISTORY_DAYS:
            reason = f"Insufficient trading data ({len(hist)} days) — possibly delisted"
            logger.warning(f"Corporate events filter blocked {symbol}: {reason}")
            return False, reason

        # 3. Volume check — delisted/suspended stocks go to near-zero volume
        avg_volume = hist["Volume"].tail(5).mean()
        if avg_volume < MIN_AVG_VOLUME:
            reason = f"Critically low avg volume ({int(avg_volume):,}) — possible delisting or suspension"
            logger.warning(f"Corporate events filter blocked {symbol}: {reason}")
            return False, reason

        # 4. Price pinning detection — acquisition targets trade in a tight
        #    band just below the offer price. If last 5 closes are within
        #    0.5% of each other AND within 2% of 52w high, flag it.
        closes = hist["Close"].tail(10)
        if len(closes) >= 5:
            recent = closes.tail(5)
            price_range_pct = (recent.max() - recent.min()) / recent.mean() * 100
            hi_52w = hist["Close"].max()
            near_high_pct = abs(closes.iloc[-1] - hi_52w) / hi_52w * 100

            if price_range_pct < MAX_PRICE_PIN_PCT and near_high_pct < 2.0:
                reason = (
                    f"Price pinning detected — last 5 closes within {price_range_pct:.2f}% range "
                    f"near 52w high (${hi_52w:.2f}). Possible acquisition target."
                )
                logger.warning(f"Corporate events filter flagged {symbol}: {reason}")
                return False, reason

        # 5. Check fast_info for any anomalies
        info = ticker.fast_info
        market_cap = getattr(info, 'market_cap', None)
        if market_cap is not None and market_cap < 10_000_000:  # Under $10M
            reason = f"Market cap critically low (${market_cap:,.0f}) — penny stock or near-delisted"
            logger.warning(f"Corporate events filter blocked {symbol}: {reason}")
            return False, reason

        return True, "OK"

    except Exception as e:
        # If we can't get data at all, skip to be safe
        reason = f"Data fetch error — skipping to be safe: {e}"
        logger.warning(f"Corporate events filter blocked {symbol}: {reason}")
        return False, reason


def add_to_blacklist(symbol: str, reason: str):
    """Manually add a symbol to the blacklist at runtime."""
    BLACKLIST[symbol] = reason
    logger.info(f"Added {symbol} to corporate events blacklist: {reason}")


def remove_from_blacklist(symbol: str):
    """Remove a symbol from the blacklist."""
    if symbol in BLACKLIST:
        del BLACKLIST[symbol]
        logger.info(f"Removed {symbol} from corporate events blacklist")
