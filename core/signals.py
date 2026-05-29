"""
Signal Engine
=============
Calculates RSI, Bollinger Bands, and Z-score for a given price series.
Returns a Signal object with direction and confirmation count.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
from config.settings import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    BBAND_PERIOD, BBAND_STD,
    ZSCORE_PERIOD, ZSCORE_THRESHOLD,
    MIN_SIGNALS
)


@dataclass
class Signal:
    symbol: str
    direction: str          # "BUY", "SELL", or "NONE"
    confirmations: int      # How many indicators agreed
    rsi: float
    rsi_signal: str
    bband_signal: str
    zscore: float
    zscore_signal: str
    close_price: float
    reason: str


def compute_rsi(prices: pd.Series, period: int = RSI_PERIOD) -> float:
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)


def compute_bollinger(prices: pd.Series, period: int = BBAND_PERIOD, std: float = BBAND_STD):
    ma = prices.rolling(period).mean()
    sd = prices.rolling(period).std()
    upper = ma + std * sd
    lower = ma - std * sd
    return upper.iloc[-1], ma.iloc[-1], lower.iloc[-1]


def compute_zscore(prices: pd.Series, period: int = ZSCORE_PERIOD) -> float:
    window = prices.tail(period)
    z = (prices.iloc[-1] - window.mean()) / window.std()
    return round(z, 3)


def evaluate(symbol: str, prices: pd.Series, market_trend: str = None) -> Signal:
    """
    Evaluate all three indicators and return a Signal.
    Requires at least BBAND_PERIOD + 5 data points.
    """
    if len(prices) < BBAND_PERIOD + 5:
        return Signal(symbol, "NONE", 0, 0, "NONE", "NONE", 0, "NONE", prices.iloc[-1], "Insufficient data")

    close = prices.iloc[-1]
    rsi = compute_rsi(prices)
    upper, mid, lower = compute_bollinger(prices)
    zscore = compute_zscore(prices)

    buy_votes  = 0
    sell_votes = 0

    # --- RSI ---
    if rsi < RSI_OVERSOLD:
        rsi_signal = "BUY"
        buy_votes += 1
    elif rsi > RSI_OVERBOUGHT:
        rsi_signal = "SELL"
        sell_votes += 1
    else:
        rsi_signal = "NONE"

    # --- Bollinger Bands ---
    if close <= lower:
        bband_signal = "BUY"
        buy_votes += 1
    elif close >= upper:
        bband_signal = "SELL"
        sell_votes += 1
    else:
        bband_signal = "NONE"

    # --- Z-Score ---
    if zscore <= -ZSCORE_THRESHOLD:
        zscore_signal = "BUY"
        buy_votes += 1
    elif zscore >= ZSCORE_THRESHOLD:
        zscore_signal = "SELL"
        sell_votes += 1
    else:
        zscore_signal = "NONE"

    # --- Confirmation Gate ---
    if buy_votes >= MIN_SIGNALS:
        direction = "BUY"
        confirmations = buy_votes
        reason = f"RSI={rsi_signal} BB={bband_signal} Z={zscore_signal} ({buy_votes}/3 BUY)"
    elif sell_votes >= MIN_SIGNALS:
        direction = "SELL"
        confirmations = sell_votes
        reason = f"RSI={rsi_signal} BB={bband_signal} Z={zscore_signal} ({sell_votes}/3 SELL)"
    else:
        direction = "NONE"
        confirmations = max(buy_votes, sell_votes)
        reason = f"No consensus — RSI={rsi_signal} BB={bband_signal} Z={zscore_signal}"

    return Signal(
        symbol=symbol,
        direction=direction,
        confirmations=confirmations,
        rsi=rsi,
        rsi_signal=rsi_signal,
        bband_signal=bband_signal,
        zscore=zscore,
        zscore_signal=zscore_signal,
        close_price=round(close, 4),
        reason=reason
    )
