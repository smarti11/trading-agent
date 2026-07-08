"""
Options Data Fetcher
====================
Pulls option chains and quotes via yfinance.
Suitable for paper trading and signal research; use broker quotes for live.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import yfinance as yf

from core.options.chain import OptionsContract, pick_expiration, select_contract, _parse_expiration
from data.fetcher import get_symbol_data

logger = logging.getLogger("options_agent")


def get_expirations(underlying: str) -> list[date]:
  try:
    ticker = yf.Ticker(underlying)
    expirations = ticker.options or []
    return [_parse_expiration(e) for e in expirations]
  except Exception as e:
    logger.warning(f"{underlying}: failed to fetch expirations — {e}")
    return []


def get_chain_for_expiration(underlying: str, expiration: date):
  try:
    ticker = yf.Ticker(underlying)
    exp_str = expiration.strftime("%Y-%m-%d")
    chain = ticker.option_chain(exp_str)
    return chain.calls, chain.puts
  except Exception as e:
    logger.warning(f"{underlying} {expiration}: chain fetch failed — {e}")
    return None, None


def get_option_premium(contract: OptionsContract) -> float:
  """Return best available mark for a contract."""
  if contract.mid > 0:
    return contract.mid
  try:
    ticker = yf.Ticker(contract.underlying)
    exp_str = contract.expiration.strftime("%Y-%m-%d")
    chain = ticker.option_chain(exp_str)
    df = chain.calls if contract.option_type == "CALL" else chain.puts
    row = df[df["strike"] == contract.strike]
    if row.empty:
      return contract.last or 0.0
    bid = float(row.iloc[0].get("bid", 0) or 0)
    ask = float(row.iloc[0].get("ask", 0) or 0)
    if bid > 0 and ask > 0:
      return round((bid + ask) / 2, 4)
    return float(row.iloc[0].get("lastPrice", 0) or 0)
  except Exception as e:
    logger.warning(f"Premium fetch failed for {contract.contract_symbol}: {e}")
    return contract.last or contract.mid or 0.0


def find_tradeable_contract(
    underlying: str,
    direction: str,
) -> tuple[Optional[OptionsContract], str]:
  """
  Full pipeline: underlying price → expiration → strike selection.
  direction: BUY → call, SELL → put
  """
  sym_data = get_symbol_data(underlying)
  if sym_data is None:
    return None, "Insufficient underlying data"

  underlying_price = sym_data.current_price
  if not underlying_price or underlying_price <= 0:
    return None, "Missing underlying price"

  expirations = get_expirations(underlying)
  expiration = pick_expiration(expirations)
  if expiration is None:
    return None, f"No expiration in {underlying} chain within DTE window"

  calls, puts = get_chain_for_expiration(underlying, expiration)
  if calls is None:
    return None, "Options chain unavailable"

  return select_contract(
    underlying, direction, calls, puts, expiration, underlying_price
  )


def get_open_position_premiums(positions: list) -> dict[str, float]:
  """Fetch current premium marks for open option positions."""
  premiums: dict[str, float] = {}
  for pos in positions:
    contract = OptionsContract(
      underlying=pos["underlying"],
      option_type=pos["option_type"],
      strike=float(pos["strike"]),
      expiration=date.fromisoformat(pos["expiration"]),
      bid=0, ask=0, last=0, volume=0, open_interest=0,
      implied_volatility=0, in_the_money=False,
      contract_symbol=pos["contract_symbol"],
    )
    premium = get_option_premium(contract)
    if premium:
      premiums[pos["contract_symbol"]] = premium
  return premiums
