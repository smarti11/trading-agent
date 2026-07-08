"""
Options Order Placement
=======================
Extends E*Trade client with long call / long put order support.
"""

import logging
from datetime import datetime, date

from broker.etrade import ETradeClient
from core.options.chain import OptionsContract
from config.options_settings import OPTIONS_TRADE_AMOUNT_USD, OPTIONS_PAPER_TRADING

logger = logging.getLogger("options_agent")


def _etrade_order_action(option_type: str, opening: bool) -> str:
  """Map to E*Trade orderAction for long options only."""
  if opening:
    return "BUY_OPEN"
  return "SELL_CLOSE"


class OptionsBroker(ETradeClient):
  """E*Trade client with options order helpers."""

  def calculate_contracts(self, premium_per_contract: float) -> int:
    """How many contracts fit in OPTIONS_TRADE_AMOUNT_USD budget."""
    if premium_per_contract <= 0:
      return 0
    cost_per = premium_per_contract * 100
    contracts = int(OPTIONS_TRADE_AMOUNT_USD / cost_per)
    return max(contracts, 0)

  def place_option_order(
      self,
      contract: OptionsContract,
      contracts: int,
      opening: bool = True,
  ) -> dict:
    if contracts < 1:
      raise ValueError("contracts must be >= 1")

    action = _etrade_order_action(contract.option_type, opening)
    symbol = contract.underlying

    if self.paper or OPTIONS_PAPER_TRADING:
      logger.info(
        f"[PAPER] Simulated option order: {action} {contracts}x "
        f"{contract.contract_symbol} @ ${contract.mid}"
      )
      return {
        "simulated": True,
        "action": action,
        "contract": contract.contract_symbol,
        "contracts": contracts,
        "status": "PAPER_FILLED",
      }

    if not self.account_id:
      self.get_account_id()

    exp = contract.expiration
    order_payload = {
      "PlaceOrderRequest": {
        "orderType": "OPTN",
        "clientOrderId": str(int(datetime.now().timestamp())),
        "Order": [{
          "Instrument": [{
            "Product": {
              "securityType": "OPTN",
              "symbol": symbol,
              "callPut": contract.option_type,
              "strikePrice": contract.strike,
              "expiryYear": exp.year,
              "expiryMonth": exp.month,
              "expiryDay": exp.day,
            },
            "orderAction": action,
            "quantityType": "QUANTITY",
            "quantity": contracts,
          }],
          "orderTerm": "GOOD_FOR_DAY",
          "priceType": "MARKET",
          "marketSession": "REGULAR",
        }]
      }
    }
    url = f"{self.base}/v1/accounts/{self.account_id}/orders/place.json"
    logger.info(
      f"[LIVE] Placing option order: {action} {contracts}x "
      f"{contract.contract_symbol}"
    )
    resp = self.session.post(url, json=order_payload)
    resp.raise_for_status()
    result = resp.json()
    logger.info(f"Option order response: {result}")
    return result
