"""Pre-open gap scanner for open positions."""

import logging
import yfinance as yf
from config.settings import PREOPEN_GAP_PCT

logger = logging.getLogger("trading_agent")


def check_preopen_gaps(open_positions) -> list:
    """
    Check premarket prices for all open positions.
    Returns list of (symbol, premarket_price, gap_pct) for positions
    where the gap is adverse and exceeds PREOPEN_GAP_PCT.
    gap_pct is negative = adverse move against the position.
    """
    results = []
    for pos in open_positions:
        symbol = pos["symbol"]
        entry_price = pos["entry_price"]
        action = pos["action"]
        try:
            pre_price = yf.Ticker(symbol).fast_info.pre_market_price
            if pre_price is None:
                continue
            pre_price = float(pre_price)
            # Adverse gap: BUY position with price below entry; SELL with price above entry
            if action == "BUY":
                gap_pct = (pre_price - entry_price) / entry_price
            else:
                gap_pct = (entry_price - pre_price) / entry_price
            if gap_pct <= -PREOPEN_GAP_PCT:
                logger.warning(
                    f"Pre-open gap alert: {symbol} @ ${pre_price:.3f} "
                    f"({gap_pct*100:+.1f}% vs entry ${entry_price:.3f}) — queuing close"
                )
                results.append((symbol, pre_price, gap_pct))
        except Exception as e:
            logger.debug(f"Preopen check failed for {symbol}: {e}")
    return results
