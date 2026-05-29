"""
ATR (Average True Range) Module
================================
Provides ATR-based filters and dynamic stop/take calculations.

Two uses:
1. Volatility filter — skip symbols where ATR/price > threshold (too volatile)
2. Dynamic stops — ATR-based stop loss / take profit (for live trading)

Usage:
    from core.atr import atr_filter, get_atr_stops
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger("trading_agent")

# ── Configuration ──────────────────────────────────────────────────────
ATR_PERIOD          = 14        # Standard ATR period
ATR_VOLATILITY_MAX  = 0.05      # Skip if ATR/price > 5% (too volatile)
ATR_VOLATILITY_MIN  = 0.003     # Skip if ATR/price < 0.3% (too thin/illiquid)
ATR_STOP_MULTIPLIER = 1.5       # Stop loss = 1.5x ATR from entry
ATR_TAKE_MULTIPLIER = 2.5       # Take profit = 2.5x ATR from entry
ATR_BULL_BUY_MAX    = 0.065     # Looser ATR cap for BUY in BULL market (6.5%)


def compute_atr(prices: pd.Series, highs: pd.Series, lows: pd.Series, period: int = ATR_PERIOD) -> pd.Series:
    """
    Compute Average True Range.
    True Range = max of:
      - High - Low
      - |High - Previous Close|
      - |Low - Previous Close|
    """
    prev_close = prices.shift(1)
    tr1 = highs - lows
    tr2 = (highs - prev_close).abs()
    tr3 = (lows - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(span=period, min_periods=period).mean()
    return atr


def compute_atr_from_close(prices: pd.Series, period: int = ATR_PERIOD) -> float:
    """
    Simplified ATR using only closing prices when OHLC not available.
    Uses price range approximation.
    """
    returns = prices.pct_change().abs()
    atr_pct = returns.ewm(span=period, min_periods=period).mean().iloc[-1]
    return round(float(atr_pct * prices.iloc[-1]), 4)


def atr_filter(symbol: str, prices: pd.Series, highs: pd.Series = None, lows: pd.Series = None, direction: str = None, market_trend: str = None) -> tuple:
    """
    Returns (tradeable: bool, reason: str, atr: float, atr_pct: float)

    Filters out symbols that are:
    - Too volatile (ATR/price > ATR_VOLATILITY_MAX) — whipsaw risk
    - Too thin (ATR/price < ATR_VOLATILITY_MIN) — no movement, signal noise
    """
    try:
        current_price = float(prices.iloc[-1])
        if current_price <= 0:
            return False, "Invalid price", 0, 0

        # Compute ATR
        if highs is not None and lows is not None and len(highs) >= ATR_PERIOD:
            atr_series = compute_atr(prices, highs, lows)
            atr = round(float(atr_series.iloc[-1]), 4)
        else:
            atr = compute_atr_from_close(prices)

        atr_pct = round(atr / current_price * 100, 2)

        # Too volatile — high whipsaw risk
        # Use looser cap for BUY signals in BULL market (buying dips is lower risk)
        if direction == "BUY" and market_trend == "BULL":
            max_atr = ATR_BULL_BUY_MAX
        else:
            max_atr = ATR_VOLATILITY_MAX

        if atr_pct > max_atr * 100:
            reason = f"ATR filter: {symbol} too volatile — ATR={atr_pct:.1f}% (max {max_atr*100:.0f}%)"
            logger.info(f"ATR blocked {symbol}: {reason}")
            return False, reason, atr, atr_pct

        # Too thin — not enough movement for mean reversion
        if atr_pct < ATR_VOLATILITY_MIN * 100:
            reason = f"ATR filter: {symbol} too illiquid — ATR={atr_pct:.2f}% (min {ATR_VOLATILITY_MIN*100:.1f}%)"
            logger.info(f"ATR blocked {symbol}: {reason}")
            return False, reason, atr, atr_pct

        return True, f"ATR={atr_pct:.1f}% OK", atr, atr_pct

    except Exception as e:
        logger.warning(f"ATR filter error for {symbol}: {e}")
        return True, "ATR check skipped", 0, 0


def get_atr_stops(action: str, entry_price: float, atr: float) -> tuple:
    """
    Calculate ATR-based stop loss and take profit.
    Use this instead of fixed % stops when going live.

    BUY:  stop = entry - (1.5 * ATR), take = entry + (2.5 * ATR)
    SELL: stop = entry + (1.5 * ATR), take = entry - (2.5 * ATR)
    """
    if action == "BUY":
        stop = round(entry_price - ATR_STOP_MULTIPLIER * atr, 4)
        take = round(entry_price + ATR_TAKE_MULTIPLIER * atr, 4)
    else:
        stop = round(entry_price + ATR_STOP_MULTIPLIER * atr, 4)
        take = round(entry_price - ATR_TAKE_MULTIPLIER * atr, 4)
    return stop, take


def overextension_check(symbol: str, prices: pd.Series, highs: pd.Series = None, lows: pd.Series = None) -> tuple:
    """
    Detects if price has moved too far too fast (overextension).
    Returns (overextended: bool, reason: str)

    If today's move > 2x ATR, the stock is overextended and likely to
    mean-revert further — actually a STRONGER signal, not a reason to skip.
    If today's move > 3x ATR, the stock may be in a news-driven move
    that won't revert — skip it.
    """
    try:
        if len(prices) < ATR_PERIOD + 2:
            return False, "Insufficient data"

        if highs is not None and lows is not None:
            atr_series = compute_atr(prices, highs, lows)
        else:
            atr = compute_atr_from_close(prices)
            today_move = abs(float(prices.iloc[-1]) - float(prices.iloc[-2]))
            atr_val = atr
            ratio = round(today_move / atr_val, 2) if atr_val > 0 else 0

            if ratio > 3.0:
                return True, f"Overextended: today moved {ratio:.1f}x ATR — possible news event, skip"
            return False, f"Move = {ratio:.1f}x ATR (normal)"

        atr_val = float(atr_series.iloc[-1])
        today_move = abs(float(prices.iloc[-1]) - float(prices.iloc[-2]))
        ratio = round(today_move / atr_val, 2) if atr_val > 0 else 0

        if ratio > 3.0:
            return True, f"Overextended: today moved {ratio:.1f}x ATR — possible news event, skip"
        return False, f"Move = {ratio:.1f}x ATR (normal)"

    except Exception as e:
        return False, f"Overextension check error: {e}"
