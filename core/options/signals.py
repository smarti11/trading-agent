"""
Options Signal Engine
=====================
Reuses the equity mean-reversion indicators and maps direction
to long call / long put entries.
"""

from dataclasses import dataclass

from core.signals import evaluate, Signal
from core.market_trend import is_trade_allowed
from config.options_settings import ALLOW_CALLS, ALLOW_PUTS, REQUIRE_MARKET_TREND


@dataclass
class OptionsSignal:
  underlying: str
  direction: str          # "BUY" (call) or "SELL" (put) or "NONE"
  equity_signal: Signal
  reason: str


def evaluate_options(
    symbol: str,
    prices,
    market_trend: str | None = None,
) -> OptionsSignal:
  """Translate equity mean-reversion signal into an options entry direction."""
  equity = evaluate(symbol, prices, market_trend=market_trend)

  if equity.direction == "NONE":
    return OptionsSignal(symbol, "NONE", equity, equity.reason)

  if equity.direction == "BUY" and not ALLOW_CALLS:
    return OptionsSignal(symbol, "NONE", equity, "CALL entries disabled")

  if equity.direction == "SELL" and not ALLOW_PUTS:
    return OptionsSignal(symbol, "NONE", equity, "PUT entries disabled")

  if REQUIRE_MARKET_TREND:
    allowed, trend_reason = is_trade_allowed(equity.direction)
    if not allowed:
      return OptionsSignal(symbol, "NONE", equity, trend_reason)

  option_desc = "long call" if equity.direction == "BUY" else "long put"
  reason = f"{equity.reason} → {option_desc}"
  return OptionsSignal(symbol, equity.direction, equity, reason)
