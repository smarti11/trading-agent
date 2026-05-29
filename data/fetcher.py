"""
Data Module
===========
Fetches the most active stocks for the day and pulls OHLCV history
using yfinance (free, no API key needed).
"""

import yfinance as yf
import pandas as pd
import requests
import logging
from config.settings import TOP_ACTIVE_COUNT

logger = logging.getLogger("trading_agent")

# Fallback static watchlist if scraping fails
FALLBACK_SYMBOLS = [
    "AAPL","TSLA","NVDA","AMD","AMZN","MSFT","META","GOOGL","SPY","QQQ",
    "SOFI","PLTR","BAC","F","T","INTC","WFC","C","XOM","JPM",
    "BABA","NIO","UBER","LYFT","RIVN","LCID","GME","AMC","HOOD","SNAP"
]


def get_most_active(n: int = TOP_ACTIVE_COUNT) -> list[str]:
    """
    Fetch the most active US stock symbols for today.
    Uses Yahoo Finance's most-active screener endpoint.
    Falls back to a static list if the request fails.
    """
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


def get_price_history(symbol: str, period: str = "60d", interval: str = "1d"):
    """
    Returns a pandas Series of closing prices for the symbol.
    period: how far back ('60d', '1y', etc.)
    interval: bar size ('1d', '1h', '5m')
    """
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty or len(df) < 25:
            logger.warning(f"{symbol}: insufficient history ({len(df)} bars)")
            return None
        return df["Close"].dropna()
    except Exception as e:
        logger.warning(f"{symbol}: history fetch error — {e}")
        return None


def get_ohlc_history(symbol: str, period: str = "60d", interval: str = "1d"):
    """
    Returns a DataFrame with Open, High, Low, Close columns for ATR calculation.
    Returns None if insufficient data.
    """
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty or len(df) < 20:
            return None
        return df[["Open", "High", "Low", "Close"]].dropna()
    except Exception as e:
        logger.warning(f"{symbol}: OHLC fetch error — {e}")
        return None


def get_current_price(symbol: str):
    """Fast single-price fetch."""
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.fast_info
        return round(data.last_price, 4)
    except Exception:
        return None
