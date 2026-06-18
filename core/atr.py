"""
ATR (Average True Range) Module
================================
Provides ATR-based filters and dynamic stop/take calculations.
"""

import numpy as np
import pandas as pd
import logging

from config.settings import (
    ATR_PERIOD,
    ATR_VOLATILITY_MAX,
    ATR_VOLATILITY_MIN,
    ATR_BULL_BUY_MAX,
    ATR_STOP_MULTIPLIER,
    ATR_TAKE_MULTIPLIER,
)

logger = logging.getLogger("trading_agent")


def compute_atr(prices: pd.Series, highs: pd.Series, lows: pd.Series, period: int = ATR_PERIOD) -> pd.Series:
    """Compute Average True Range."""
    prev_close = prices.shift(1)
    tr1 = highs - lows
    tr2 = (highs - prev_close).abs()
    tr3 = (lows - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(span=period, min_periods=period).mean()
    return atr


def compute_atr_from_close(prices: pd.Series, period: int = ATR_PERIOD) -> float:
    """Simplified ATR using only closing prices when OHLC not available."""
    returns = prices.pct_change().abs()
    atr_pct = returns.ewm(span=period, min_periods=period).mean().iloc[-1]
    return round(float(atr_pct * prices.iloc[-1]), 4)


def atr_filter(symbol: str, prices: pd.Series, highs: pd.Series = None, lows: pd.Series = None,
               direction: str = None, market_trend: str = None) -> tuple:
    """
    Returns (tradeable: bool, reason: str, atr: float, atr_pct: float)
    """
    try:
        current_price = float(prices.iloc[-1])
        if current_price <= 0:
            return False, "Invalid price", 0, 0

        if highs is not None and lows is not None and len(highs) >= ATR_PERIOD:
            atr_series = compute_atr(prices, highs, lows)
            atr = round(float(atr_series.iloc[-1]), 4)
        else:
            atr = compute_atr_from_close(prices)

        atr_pct = round(atr / current_price * 100, 2)

        if direction == "BUY" and market_trend == "BULL":
            max_atr = ATR_BULL_BUY_MAX
        else:
            max_atr = ATR_VOLATILITY_MAX

        if atr_pct > max_atr * 100:
            reason = f"ATR filter: {symbol} too volatile — ATR={atr_pct:.1f}% (max {max_atr*100:.0f}%)"
            logger.info(f"ATR blocked {symbol}: {reason}")
            return False, reason, atr, atr_pct

        if atr_pct < ATR_VOLATILITY_MIN * 100:
            reason = f"ATR filter: {symbol} too illiquid — ATR={atr_pct:.2f}% (min {ATR_VOLATILITY_MIN*100:.1f}%)"
            logger.info(f"ATR blocked {symbol}: {reason}")
            return False, reason, atr, atr_pct

        return True, f"ATR={atr_pct:.1f}% OK", atr, atr_pct

    except Exception as e:
        logger.warning(f"ATR filter error for {symbol}: {e}")
        return True, "ATR check skipped", 0, 0


def get_atr_stops(action: str, entry_price: float, atr: float) -> tuple:
    """Calculate ATR-based stop loss and take profit."""
    if action == "BUY":
        stop = round(entry_price - ATR_STOP_MULTIPLIER * atr, 4)
        take = round(entry_price + ATR_TAKE_MULTIPLIER * atr, 4)
    else:
        stop = round(entry_price + ATR_STOP_MULTIPLIER * atr, 4)
        take = round(entry_price - ATR_TAKE_MULTIPLIER * atr, 4)
    return stop, take


def overextension_check(symbol: str, prices: pd.Series, highs: pd.Series = None, lows: pd.Series = None) -> tuple:
    """Skip symbols with news-driven moves > 3x ATR."""
    try:
        if len(prices) < ATR_PERIOD + 2:
            return False, "Insufficient data"

        if highs is not None and lows is not None:
            atr_series = compute_atr(prices, highs, lows)
            atr_val = float(atr_series.iloc[-1])
        else:
            atr_val = compute_atr_from_close(prices)

        today_move = abs(float(prices.iloc[-1]) - float(prices.iloc[-2]))
        ratio = round(today_move / atr_val, 2) if atr_val > 0 else 0

        if ratio > 3.0:
            return True, f"Overextended: today moved {ratio:.1f}x ATR — possible news event, skip"
        return False, f"Move = {ratio:.1f}x ATR (normal)"

    except Exception as e:
        return False, f"Overextension check error: {e}"
