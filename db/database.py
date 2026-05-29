"""
Database Module
===============
SQLite-backed trade log, signal log, and P&L tracker.
Auto-creates tables on first run.
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from config.settings import DB_PATH

logger = logging.getLogger("trading_agent")


def get_conn():
    Path(DB_PATH).parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            direction   TEXT NOT NULL,
            confirmations INTEGER,
            rsi         REAL,
            rsi_signal  TEXT,
            bband_signal TEXT,
            zscore      REAL,
            zscore_signal TEXT,
            close_price REAL,
            reason      TEXT
        );

        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            action      TEXT NOT NULL,
            quantity    INTEGER,
            price       REAL,
            amount_usd  REAL,
            mode        TEXT NOT NULL,
            status      TEXT NOT NULL,
            order_ref   TEXT,
            signal_id   INTEGER,
            notes       TEXT
        );

        CREATE TABLE IF NOT EXISTS positions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT UNIQUE NOT NULL,
            action      TEXT NOT NULL,
            quantity    INTEGER,
            entry_price REAL,
            entry_ts    TEXT,
            stop_loss   REAL,
            take_profit REAL,
            status      TEXT DEFAULT 'OPEN'
        );

        CREATE TABLE IF NOT EXISTS pnl (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT,
            entry_price REAL,
            exit_price  REAL,
            quantity    INTEGER,
            pnl_usd     REAL,
            pnl_pct     REAL,
            entry_ts    TEXT,
            exit_ts     TEXT
        );

        CREATE TABLE IF NOT EXISTS strategy_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            version     TEXT NOT NULL,
            description TEXT
        );
        """)
        # Idempotent migration: add strategy_version column to trades if absent
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN strategy_version TEXT")
        except Exception:
            pass
    logger.info("Database initialized")


def log_signal(signal) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO signals (ts, symbol, direction, confirmations, rsi, rsi_signal,
                bband_signal, zscore, zscore_signal, close_price, reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(), signal.symbol, signal.direction,
            signal.confirmations, signal.rsi, signal.rsi_signal,
            signal.bband_signal, signal.zscore, signal.zscore_signal,
            signal.close_price, signal.reason
        ))
        return cur.lastrowid


def log_trade(symbol, action, quantity, price, mode, status, order_ref=None, signal_id=None, notes=None, strategy_version=None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO trades (ts, symbol, action, quantity, price, amount_usd, mode, status, order_ref, signal_id, notes, strategy_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(), symbol, action, quantity, price,
            round(quantity * price, 2), mode, status, order_ref, signal_id, notes, strategy_version
        ))


def open_position(symbol, action, quantity, entry_price, stop_loss, take_profit):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO positions (symbol, action, quantity, entry_price, entry_ts, stop_loss, take_profit, status)
            VALUES (?,?,?,?,?,?,?,'OPEN')
        """, (symbol, action, quantity, entry_price, datetime.now().isoformat(), stop_loss, take_profit))


def close_position(symbol, exit_price):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM positions WHERE symbol=? AND status='OPEN'", (symbol,)).fetchone()
        if not row:
            return
        pnl_usd = (exit_price - row["entry_price"]) * row["quantity"]
        if row["action"] == "SELL":
            pnl_usd = -pnl_usd
        pnl_pct = pnl_usd / (row["entry_price"] * row["quantity"]) * 100
        conn.execute("UPDATE positions SET status='CLOSED' WHERE symbol=?", (symbol,))
        conn.execute("""
            INSERT INTO pnl (symbol, entry_price, exit_price, quantity, pnl_usd, pnl_pct, entry_ts, exit_ts)
            VALUES (?,?,?,?,?,?,?,?)
        """, (symbol, row["entry_price"], exit_price, row["quantity"],
              round(pnl_usd, 2), round(pnl_pct, 3), row["entry_ts"], datetime.now().isoformat()))
        logger.info(f"Closed {symbol} | P&L: ${pnl_usd:+.2f} ({pnl_pct:+.2f}%)")


def get_open_positions() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall()


def was_recently_closed(symbol: str, hours: int = 24) -> bool:
    """Returns True if symbol was closed within the last N hours."""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM pnl WHERE symbol=? AND exit_ts >= ?",
            (symbol, cutoff)
        ).fetchone()
        return (row["n"] or 0) > 0


def get_day_trade_count(days: int = 5) -> int:
    """Count same-day open+close trades in the last N business days."""
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) as n FROM pnl
               WHERE exit_ts >= ? AND date(entry_ts) = date(exit_ts)""",
            (cutoff,)
        ).fetchone()
        return row["n"] or 0


def get_daily_pnl() -> float:
    today = datetime.now().date().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT SUM(pnl_usd) as total FROM pnl WHERE exit_ts LIKE ?", (f"{today}%",)
        ).fetchone()
        return row["total"] or 0.0


def stamp_strategy_version(version: str, description: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO strategy_log (ts, version, description) VALUES (?,?,?)",
            (datetime.now().isoformat(), version, description)
        )
    logger.info(f"Strategy version stamped: {version}")


def get_active_strategy_version():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM strategy_log ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def print_summary():
    with get_conn() as conn:
        trades = conn.execute("SELECT COUNT(*) as n FROM trades").fetchone()["n"]
        signals = conn.execute("SELECT COUNT(*) as n FROM signals WHERE direction != 'NONE'").fetchone()["n"]
        total_pnl = conn.execute("SELECT SUM(pnl_usd) as t FROM pnl").fetchone()["t"] or 0
        wins = conn.execute("SELECT COUNT(*) as n FROM pnl WHERE pnl_usd > 0").fetchone()["n"]
        losses = conn.execute("SELECT COUNT(*) as n FROM pnl WHERE pnl_usd <= 0").fetchone()["n"]
    print(f"\n{'='*50}")
    print(f"  TRADING AGENT SUMMARY")
    print(f"{'='*50}")
    print(f"  Actionable Signals : {signals}")
    print(f"  Trades Executed    : {trades}")
    print(f"  Wins / Losses      : {wins} / {losses}")
    print(f"  Total P&L          : ${total_pnl:+.2f}")
    print(f"{'='*50}\n")
