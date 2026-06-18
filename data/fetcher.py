"""
Data Module
===========
Fetches the most active stocks for the day and pulls OHLCV history
using yfinance (free, no API key needed).
"""

from dataclasses import dataclass
from typing import Optional

import yfinance as yf
import pandas as pd
import requests
import logging

from config.settings import TOP_ACTIVE_COUNT

logger = logging.getLogger("trading_agent")

FALLBACK_SYMBOLS = [
    "AAPL","TSLA","NVDA","AMD","AMZN","MSFT","META","GOOGL","SPY","QQQ",
    "SOFI","PLTR","BAC","F","T","INTC","WFC","C","XOM","JPM",
    "BABA","NIO","UBER","LYFT","RIVN","LCID","GME","AMC","HOOD","SNAP"
]


@dataclass
class SymbolData:
    symbol: str
    closes: pd.Series
    ohlc: Optional[pd.DataFrame]
    current_price: Optional[float]


def get_most_active(n: int = TOP_ACTIVE_COUNT) -> list[str]:
    """Fetch the most active US stock symbols for today."""
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
        params = {
            "formatted": "false",
            "lang": "en-US",
            "region": "US",
            "scrIds": "most_actives",
            "count": n,
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        quotes = data["finance"]["result"][0]["quotes"]
        symbols = [q["symbol"] for q in quotes if "." not in q["symbol"]][:n]
        logger.info(f"Fetched {len(symbols)} most-active symbols")
        return symbols
    except Exception as e:
        logger.warning(f"Most-active fetch failed ({e}), using fallback list")
        return FALLBACK_SYMBOLS[:n]


def get_symbol_data(symbol: str, period: str = "60d", interval: str = "1d") -> Optional[SymbolData]:
    """
    Single yfinance fetch returning close series, OHLC, and last price.
    Replaces separate get_price_history / get_ohlc_history / get_current_price calls.
    """
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty or len(df) < 25:
            logger.warning(f"{symbol}: insufficient history ({len(df)} bars)")
            return None

        closes = df["Close"].dropna()
        ohlc = df[["Open", "High", "Low", "Close"]].dropna()

        current_price = None
        try:
            current_price = round(float(ticker.fast_info.last_price), 4)
        except Exception:
            current_price = round(float(closes.iloc[-1]), 4)

        return SymbolData(
            symbol=symbol,
            closes=closes,
            ohlc=ohlc if len(ohlc) >= 20 else None,
            current_price=current_price,
        )
    except Exception as e:
        logger.warning(f"{symbol}: data fetch error — {e}")
        return None


def get_price_history(symbol: str, period: str = "60d", interval: str = "1d"):
    """Returns a pandas Series of closing prices for the symbol."""
    data = get_symbol_data(symbol, period, interval)
    return data.closes if data else None


def get_ohlc_history(symbol: str, period: str = "60d", interval: str = "1d"):
    """Returns OHLC DataFrame for ATR calculation."""
    data = get_symbol_data(symbol, period, interval)
    return data.ohlc if data else None


def get_current_price(symbol: str):
    """Fast single-price fetch for position monitoring."""
    try:
        ticker = yf.Ticker(symbol)
        return round(float(ticker.fast_info.last_price), 4)
    except Exception:
        return None
