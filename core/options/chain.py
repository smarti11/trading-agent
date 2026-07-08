"""
Options Chain Utilities
=======================
Contract selection, OCC symbol formatting, and chain helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import pandas as pd

from config.options_settings import (
    MIN_DTE, TARGET_DTE, MAX_DTE,
    MIN_DELTA, MAX_DELTA,
    MAX_BID_ASK_SPREAD_PCT, MIN_OPEN_INTEREST, MIN_VOLUME,
)


@dataclass
class OptionsContract:
  underlying: str
  option_type: str          # "CALL" or "PUT"
  strike: float
  expiration: date
  bid: float
  ask: float
  last: float
  volume: int
  open_interest: int
  implied_volatility: float
  in_the_money: bool
  contract_symbol: str      # OCC-style identifier for logging/DB

  @property
  def mid(self) -> float:
    if self.bid > 0 and self.ask > 0:
      return round((self.bid + self.ask) / 2, 4)
    return self.last or self.ask or self.bid or 0.0

  @property
  def dte(self) -> int:
    return (self.expiration - date.today()).days

  @property
  def spread_pct(self) -> float:
    mid = self.mid
    if mid <= 0:
      return 1.0
    return (self.ask - self.bid) / mid if self.ask and self.bid else 0.0


def build_occ_symbol(
    underlying: str,
    expiration: date,
    option_type: str,
    strike: float,
) -> str:
  """Build a human-readable OCC-style contract id for DB keys."""
  root = underlying.upper().ljust(6)[:6]
  yymmdd = expiration.strftime("%y%m%d")
  cp = "C" if option_type.upper() == "CALL" else "P"
  strike_int = int(round(strike * 1000))
  return f"{root}{yymmdd}{cp}{strike_int:08d}".replace(" ", "")


def _parse_expiration(value) -> date:
  if isinstance(value, date):
    return value
  if isinstance(value, datetime):
    return value.date()
  return pd.Timestamp(value).date()


def _estimate_delta(contract: OptionsContract, underlying_price: float) -> float:
  """
  Rough delta proxy when greeks are unavailable from the data source.
  Uses moneyness: deeper ITM → higher delta magnitude.
  """
  if underlying_price <= 0 or contract.strike <= 0:
    return 0.0
  moneyness = underlying_price / contract.strike
  if contract.option_type == "CALL":
    if contract.in_the_money:
      return min(0.85, 0.45 + (moneyness - 1.0) * 2.0)
    return max(0.15, 0.50 - (1.0 - moneyness) * 2.0)
  # PUT
  if contract.in_the_money:
    return min(0.85, 0.45 + (1.0 / moneyness - 1.0) * 2.0)
  return max(0.15, 0.50 - (moneyness - 1.0) * 2.0)


def _row_to_contract(
    underlying: str,
    option_type: str,
    expiration: date,
    row: pd.Series,
) -> OptionsContract:
  strike = float(row.get("strike", 0))
  bid = float(row.get("bid", 0) or 0)
  ask = float(row.get("ask", 0) or 0)
  last = float(row.get("lastPrice", 0) or row.get("last", 0) or 0)
  return OptionsContract(
    underlying=underlying,
    option_type=option_type,
    strike=strike,
    expiration=expiration,
    bid=bid,
    ask=ask,
    last=last,
    volume=int(row.get("volume", 0) or 0),
    open_interest=int(row.get("openInterest", 0) or 0),
    implied_volatility=float(row.get("impliedVolatility", 0) or 0),
    in_the_money=bool(row.get("inTheMoney", False)),
    contract_symbol=build_occ_symbol(underlying, expiration, option_type, strike),
  )


def select_contract(
    underlying: str,
    direction: str,
    calls_df: pd.DataFrame,
    puts_df: pd.DataFrame,
    expiration: date,
    underlying_price: float,
) -> tuple[Optional[OptionsContract], str]:
  """
  Pick the best contract for a directional signal.
  direction: "BUY" → call, "SELL" → put
  """
  option_type = "CALL" if direction == "BUY" else "PUT"
  chain = calls_df if option_type == "CALL" else puts_df
  if chain is None or chain.empty:
    return None, f"No {option_type.lower()} chain for {underlying}"

  candidates: list[tuple[float, OptionsContract]] = []
  for _, row in chain.iterrows():
    contract = _row_to_contract(underlying, option_type, expiration, row)
    if contract.dte < MIN_DTE or contract.dte > MAX_DTE:
      continue
    if contract.open_interest < MIN_OPEN_INTEREST and contract.volume < MIN_VOLUME:
      continue
    if contract.mid <= 0:
      continue
    if contract.spread_pct > MAX_BID_ASK_SPREAD_PCT:
      continue

    delta = abs(_estimate_delta(contract, underlying_price))
    if delta < MIN_DELTA or delta > MAX_DELTA:
      continue

    dte_score = abs(contract.dte - TARGET_DTE)
    delta_score = abs(delta - ((MIN_DELTA + MAX_DELTA) / 2))
    score = dte_score + delta_score * 20
    candidates.append((score, contract))

  if not candidates:
    return None, f"No liquid {option_type} passed filters for {underlying}"

  candidates.sort(key=lambda x: x[0])
  return candidates[0][1], "OK"


def pick_expiration(expirations: list[date]) -> Optional[date]:
  """Choose expiration closest to TARGET_DTE within MIN/MAX bounds."""
  today = date.today()
  valid = [e for e in expirations if MIN_DTE <= (e - today).days <= MAX_DTE]
  if not valid:
    return None
  return min(valid, key=lambda e: abs((e - today).days - TARGET_DTE))
