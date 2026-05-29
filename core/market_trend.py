"""
Market Trend Filter
====================
Determines the current market trend using SPY (S&P 500 ETF)
as a proxy for overall market direction.

Logic:
- BULL:  SPY price > 50-day MA AND 50-day MA > 200-day MA
- BEAR:  SPY price < 50-day MA AND 50-day MA < 200-day MA
- CHOP:  Mixed signals — neither clearly bull nor bear

Trade filter:
- BULL market:  Allow BUY signals, skip SELL signals
- BEAR market:  Allow SELL signals, skip BUY signals
- CHOP market:  Allow both (reversion works in both directions)

This prevents the agent from fighting the trend by:
- Not buying in a falling market
- Not shorting in a rising market
"""

import logging
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

logger = logging.getLogger("trading_agent")

# Cache the trend so we don't fetch SPY on every single signal
_trend_cache = {
    "trend":      None,
    "spy_price":  None,
    "ma50":       None,
    "ma200":      None,
    "last_check": None,
    "cache_mins": 60,   # Re-check every 60 minutes
}


def get_market_trend(force_refresh: bool = False) -> dict:
    """
    Returns current market trend based on SPY moving averages.
    
    Returns:
        {
            "trend":     "BULL" | "BEAR" | "CHOP",
            "spy_price": float,
            "ma50":      float,
            "ma200":     float,
            "allow_buy": bool,
            "allow_sell": bool,
            "reason":    str
        }
    """
    global _trend_cache

    # Use cache if fresh enough
    if (not force_refresh and
        _trend_cache["last_check"] is not None and
        _trend_cache["trend"] is not None):
        mins_since = (datetime.now() - _trend_cache["last_check"]).seconds / 60
        if mins_since < _trend_cache["cache_mins"]:
            return _trend_cache.copy()

    try:
        # Fetch 1 year of SPY daily data
        spy = yf.download("SPY", period="1y", interval="1d", progress=False, auto_adjust=True)
        if spy.empty or len(spy) < 50:
            logger.warning("Market trend: insufficient SPY data — defaulting to CHOP")
            return _default_trend("Insufficient SPY data")

        closes = spy["Close"].squeeze()

        spy_price = float(closes.iloc[-1])
        ma50      = float(closes.tail(50).mean())
        ma200     = float(closes.tail(200).mean()) if len(closes) >= 200 else float(closes.mean())

        # Determine trend
        price_above_ma50  = spy_price > ma50
        ma50_above_ma200  = ma50 > ma200
        price_below_ma50  = spy_price < ma50
        ma50_below_ma200  = ma50 < ma200

        if price_above_ma50 and ma50_above_ma200:
            trend      = "BULL"
            allow_buy  = True
            allow_sell = False
            reason     = f"SPY ${spy_price:.2f} > MA50 ${ma50:.2f} > MA200 ${ma200:.2f} — BULL market"
        elif price_below_ma50 and ma50_below_ma200:
            trend      = "BEAR"
            allow_buy  = False
            allow_sell = True
            reason     = f"SPY ${spy_price:.2f} < MA50 ${ma50:.2f} < MA200 ${ma200:.2f} — BEAR market"
        else:
            trend      = "CHOP"
            allow_buy  = True
            allow_sell = True
            reason     = f"SPY ${spy_price:.2f} mixed vs MA50 ${ma50:.2f} / MA200 ${ma200:.2f} — CHOP market"

        result = {
            "trend":      trend,
            "spy_price":  round(spy_price, 2),
            "ma50":       round(ma50, 2),
            "ma200":      round(ma200, 2),
            "allow_buy":  allow_buy,
            "allow_sell": allow_sell,
            "reason":     reason,
            "last_check": datetime.now(),
            "cache_mins": 60,
        }

        _trend_cache = result
        logger.info(f"Market trend: {trend} | {reason}")
        return result

    except Exception as e:
        logger.warning(f"Market trend check failed: {e} — defaulting to CHOP")
        return _default_trend(f"Error: {e}")


def _default_trend(reason: str) -> dict:
    """Default to CHOP (allow all trades) when trend can't be determined."""
    return {
        "trend":      "CHOP",
        "spy_price":  None,
        "ma50":       None,
        "ma200":      None,
        "allow_buy":  True,
        "allow_sell": True,
        "reason":     reason,
        "last_check": datetime.now(),
        "cache_mins": 60,
    }


def is_trade_allowed(direction: str) -> tuple:
    """
    Check if a trade direction is allowed given current market trend.
    
    Args:
        direction: "BUY" or "SELL"
    
    Returns:
        (allowed: bool, reason: str)
    """
    trend_data = get_market_trend()
    trend = trend_data["trend"]

    if direction == "BUY" and not trend_data["allow_buy"]:
        return False, f"Market trend BEAR — skipping BUY signals ({trend_data['reason']})"
    
    if direction == "SELL" and not trend_data["allow_sell"]:
        return False, f"Market trend BULL — skipping SELL signals ({trend_data['reason']})"
    
    return True, f"Market trend {trend} — {direction} allowed"
