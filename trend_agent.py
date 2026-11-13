"""
SPY 200-Day Trend Agent
=======================
Runs once per trading day near the close (launchd, ~3:50 PM ET):

  1. Gets SPY's current price and its 200-day simple moving average
     (today's live price stands in for today's close).
  2. Above the average -> hold SPY.  Below -> hold SGOV (T-bills).
  3. If the holding has to change, sells the old one and buys the new one
     with everything.

Paper mode (config.settings.PAPER_TRADING) fills at the current price and
keeps the account in db/trend.db. It needs no E*Trade login.

Usage:
  python trend_agent.py            # run today's check (once per day)
  python trend_agent.py --dry-run  # show the decision, change nothing
  python trend_agent.py --status   # show holdings and history
  python trend_agent.py --force    # run again even if today is done
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, date
from pathlib import Path

import yfinance as yf

from config.settings import PAPER_TRADING
from config.trend_settings import (
    TREND_SYMBOL, CASH_SYMBOL, MA_DAYS, BAND_PCT, START_CAPITAL_USD,
    DB_PATH, LOG_PATH,
)

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_PATH, mode="a")],
)
logger = logging.getLogger("trend_agent")
MODE = "PAPER" if PAPER_TRADING else "LIVE"


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cash REAL NOT NULL,
            symbol TEXT,
            shares INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, symbol TEXT NOT NULL, action TEXT NOT NULL,
            shares INTEGER NOT NULL, price REAL NOT NULL, amount_usd REAL NOT NULL,
            mode TEXT NOT NULL, reason TEXT
        );
        CREATE TABLE IF NOT EXISTS daily (
            day TEXT PRIMARY KEY, spy_price REAL, ma REAL, signal TEXT,
            holding TEXT, shares INTEGER, cash REAL, equity REAL, ts TEXT
        );
    """)
    conn.execute("INSERT OR IGNORE INTO account (id, cash, symbol, shares) VALUES (1, ?, NULL, 0)",
                 (START_CAPITAL_USD,))
    conn.commit()
    return conn


def get_account(conn) -> tuple[float, str | None, int]:
    return conn.execute("SELECT cash, symbol, shares FROM account WHERE id = 1").fetchone()


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def spy_today() -> tuple[float, float, date]:
    """Return (current SPY price, MA_DAYS average incl. today, last bar date)."""
    hist = yf.Ticker(TREND_SYMBOL).history(period="2y", interval="1d", auto_adjust=False)
    closes = hist["Close"].dropna()
    if len(closes) < MA_DAYS:
        raise RuntimeError(f"Only {len(closes)} {TREND_SYMBOL} bars; need {MA_DAYS}")
    price = float(closes.iloc[-1])
    ma = float(closes.tail(MA_DAYS).mean())
    return price, ma, closes.index[-1].date()


def last_price(symbol: str) -> float:
    closes = yf.Ticker(symbol).history(period="5d", interval="1d")["Close"].dropna()
    if closes.empty:
        raise RuntimeError(f"No price for {symbol}")
    return float(closes.iloc[-1])


def decide(price: float, ma: float, current: str | None) -> str:
    """Target holding. With a band, stay put inside it."""
    if price > ma * (1 + BAND_PCT):
        return TREND_SYMBOL
    if price < ma * (1 - BAND_PCT):
        return CASH_SYMBOL
    return current or (TREND_SYMBOL if price >= ma else CASH_SYMBOL)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

_client = None


def broker():
    """E*Trade client, only needed in live mode (asks for the daily login)."""
    global _client
    if _client is None:
        from broker.etrade import ETradeClient
        _client = ETradeClient()
        _client.authenticate()
        _client.get_account_id()
    return _client


def execute(conn, symbol: str, action: str, shares: int, price: float, reason: str):
    if shares <= 0:
        return
    if not PAPER_TRADING:
        broker().place_order(symbol, action, shares)
    amount = round(shares * price, 2)
    conn.execute(
        "INSERT INTO trades (ts, symbol, action, shares, price, amount_usd, mode, reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), symbol, action, shares, price, amount, MODE, reason),
    )
    logger.info(f"[{MODE}] {action} {shares} {symbol} @ ${price:.2f} (${amount:,.2f}) — {reason}")


def rebalance(conn, target: str, reason: str):
    cash, held, shares = get_account(conn)
    if held == target and shares > 0:
        return
    if held and shares > 0:
        p = last_price(held)
        execute(conn, held, "SELL", shares, p, reason)
        cash += shares * p
        shares, held = 0, None
    p = last_price(target)
    buy = int(cash // p)
    execute(conn, target, "BUY", buy, p, reason)
    cash -= buy * p
    conn.execute("UPDATE account SET cash = ?, symbol = ?, shares = ? WHERE id = 1",
                 (round(cash, 2), target if buy else None, buy))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def status(conn):
    cash, held, shares = get_account(conn)
    value = shares * last_price(held) if held and shares else 0.0
    equity = cash + value
    print(f"Mode: {MODE}  |  Holding: {shares} {held or '-'}  |  Cash ${cash:,.2f}  |  "
          f"Equity ${equity:,.2f}  ({100 * (equity / START_CAPITAL_USD - 1):+.2f}% since start)")
    print("\nLast 10 days:")
    for row in conn.execute("SELECT day, spy_price, ma, signal, holding, equity FROM daily "
                            "ORDER BY day DESC LIMIT 10"):
        print(f"  {row[0]}  SPY ${row[1]:.2f}  MA{MA_DAYS} ${row[2]:.2f}  {row[3]:4s}  {row[4] or '-':5s}  ${row[5]:,.2f}")
    print("\nTrades:")
    for row in conn.execute("SELECT ts, action, shares, symbol, price, reason FROM trades ORDER BY id DESC LIMIT 10"):
        print(f"  {row[0]}  {row[1]:4s} {row[2]} {row[3]} @ ${row[4]:.2f}  {row[5]}")


def main():
    ap = argparse.ArgumentParser(description="SPY 200-day trend agent")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    conn = db()
    if args.status:
        status(conn)
        return

    today = date.today()
    if not args.force and conn.execute("SELECT 1 FROM daily WHERE day = ?", (today.isoformat(),)).fetchone():
        logger.info("Already ran today — use --force to run again")
        return

    price, ma, bar_day = spy_today()
    if bar_day != today and not args.dry_run:
        logger.info(f"No {TREND_SYMBOL} session today (last bar {bar_day}) — market closed, nothing to do")
        return

    cash, held, shares = get_account(conn)
    target = decide(price, ma, held)
    signal = "IN" if target == TREND_SYMBOL else "OUT"
    gap = 100 * (price / ma - 1)
    reason = f"{TREND_SYMBOL} ${price:.2f} vs MA{MA_DAYS} ${ma:.2f} ({gap:+.2f}%) → {signal}"
    logger.info(f"--- Trend check [{MODE}] {today} | {reason} | holding {shares} {held or '-'} ---")

    if args.dry_run:
        print(f"Would hold {target}" + ("" if target == held else f" (switch from {held or 'cash'})"))
        return

    rebalance(conn, target, reason)
    cash, held, shares = get_account(conn)
    equity = cash + (shares * last_price(held) if held and shares else 0.0)
    conn.execute(
        "INSERT OR REPLACE INTO daily (day, spy_price, ma, signal, holding, shares, cash, equity, ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (today.isoformat(), price, ma, signal, held, shares, cash, round(equity, 2),
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    logger.info(f"Holding {shares} {held or '-'} | cash ${cash:,.2f} | equity ${equity:,.2f}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Trend agent failed")
        sys.exit(1)
