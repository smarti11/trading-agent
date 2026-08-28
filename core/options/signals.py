"""
Options Signal Engine — v0.2 trend-dip reclaim
==============================================
BULL-only long calls: buy the dip in an uptrend after reclaim,
not raw oversold mean-reversion.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.signals import Signal, compute_rsi
from core.market_trend import get_market_trend
from config.options_settings import (
  ALLOW_CALLS, ALLOW_PUTS, REQUIRE_BULL_ONLY,
  MA_PERIOD, DIP_RSI_LOOKBACK, DIP_RSI_MAX, RECLAIM_RSI, RSI_PERIOD,
  MIN_UNDERLYING_PRICE,
)


@dataclass
class OptionsSignal:
  underlying: str
  direction: str          # "BUY" (call) or "NONE"  — puts disabled in v0.2
  equity_signal: Signal   # diagnostic snapshot for DB logging
  reason: str


def _rsi_series(prices: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
  delta = prices.diff()
  gain = delta.clip(lower=0)
  loss = -delta.clip(upper=0)
  avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
  avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
  rs = avg_gain / avg_loss.replace(0, np.nan)
  return 100 - (100 / (1 + rs))


def _ma(prices: pd.Series, period: int = MA_PERIOD) -> float:
  return float(prices.tail(period).mean())


def _diagnostic_signal(symbol: str, prices: pd.Series, reason: str, direction: str = "NONE") -> Signal:
  close = float(prices.iloc[-1])
  try:
    rsi = compute_rsi(prices, RSI_PERIOD)
  except Exception:
    rsi = 0.0
  return Signal(
    symbol=symbol,
    direction=direction,
    confirmations=1 if direction == "BUY" else 0,
    rsi=rsi,
    rsi_signal="BUY" if direction == "BUY" else "NONE",
    bband_signal="NONE",
    zscore=0.0,
    zscore_signal="NONE",
    close_price=round(close, 4),
    reason=reason,
  )


def evaluate_options(
    symbol: str,
    prices: pd.Series,
    market_trend: str | None = None,
) -> OptionsSignal:
  """
  Enter long call only when:
    1. Market is BULL (if REQUIRE_BULL_ONLY)
    2. Underlying in uptrend (price > rising-ish 20-MA)
    3. A dip occurred (RSI < DIP_RSI_MAX within lookback)
    4. Reclaim: RSI back above RECLAIM_RSI OR close reclaimed MA after being below
  """
  if len(prices) < MA_PERIOD + RSI_PERIOD + 5:
    diag = _diagnostic_signal(symbol, prices, "Insufficient history for trend-dip")
    return OptionsSignal(symbol, "NONE", diag, diag.reason)

  close = float(prices.iloc[-1])
  if close < MIN_UNDERLYING_PRICE:
    reason = f"Underlying ${close:.2f} below ${MIN_UNDERLYING_PRICE:.0f} floor"
    diag = _diagnostic_signal(symbol, prices, reason)
    return OptionsSignal(symbol, "NONE", diag, reason)

  if not ALLOW_CALLS:
    diag = _diagnostic_signal(symbol, prices, "CALL entries disabled")
    return OptionsSignal(symbol, "NONE", diag, diag.reason)

  # Regime: BULL only
  trend_data = get_market_trend()
  trend = market_trend or trend_data.get("trend", "CHOP")
  if REQUIRE_BULL_ONLY and trend != "BULL":
    reason = f"Trend-dip requires BULL market (now {trend})"
    diag = _diagnostic_signal(symbol, prices, reason)
    return OptionsSignal(symbol, "NONE", diag, reason)

  # Puts explicitly off in v0.2
  if not ALLOW_PUTS:
    pass  # calls-only path below

  ma = _ma(prices)
  # Structure: price above MA. Allow mild MA softness during the dip itself.
  if len(prices) >= MA_PERIOD + 15:
    ma_older = float(prices.iloc[-(MA_PERIOD + 15):-15].tail(MA_PERIOD).mean())
  else:
    ma_older = ma
  uptrend = close > ma and ma >= ma_older * 0.97

  if not uptrend:
    reason = f"No uptrend: close ${close:.2f} vs MA{MA_PERIOD} ${ma:.2f}"
    diag = _diagnostic_signal(symbol, prices, reason)
    return OptionsSignal(symbol, "NONE", diag, reason)

  rsi_s = _rsi_series(prices)
  rsi_now = float(rsi_s.iloc[-1])
  rsi_window = rsi_s.iloc[-(DIP_RSI_LOOKBACK + 1):-1]  # prior N days, not today
  had_dip = bool((rsi_window < DIP_RSI_MAX).any()) if len(rsi_window) else False

  if not had_dip:
    reason = f"No recent dip (RSI<{DIP_RSI_MAX:.0f} in last {DIP_RSI_LOOKBACK}d); RSI_now={rsi_now:.1f}"
    diag = _diagnostic_signal(symbol, prices, reason)
    return OptionsSignal(symbol, "NONE", diag, reason)

  # Reclaim triggers
  rsi_reclaim = rsi_now >= RECLAIM_RSI
  # Price was below MA recently and is back above
  below_ma_recent = bool((prices.iloc[-(DIP_RSI_LOOKBACK + 1):-1] < ma).any())
  price_reclaim = close > ma and below_ma_recent

  if not (rsi_reclaim or price_reclaim):
    reason = (
      f"Dip seen but no reclaim yet (RSI={rsi_now:.1f}, need ≥{RECLAIM_RSI:.0f} "
      f"or MA reclaim)"
    )
    diag = _diagnostic_signal(symbol, prices, reason)
    return OptionsSignal(symbol, "NONE", diag, reason)

  trigger = "RSI_reclaim" if rsi_reclaim else "MA_reclaim"
  reason = (
    f"TREND_DIP BULL | {trigger} | RSI={rsi_now:.1f} "
    f"(dip<{DIP_RSI_MAX:.0f} in {DIP_RSI_LOOKBACK}d) | "
    f"close ${close:.2f} > MA{MA_PERIOD} ${ma:.2f} → long call"
  )
  diag = _diagnostic_signal(symbol, prices, reason, direction="BUY")
  return OptionsSignal(symbol, "BUY", diag, reason)
