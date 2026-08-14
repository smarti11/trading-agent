"""
Options Database
================
SQLite persistence for options signals, trades, and positions.
Uses a separate DB from the equity agent.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

from config.options_settings import OPTIONS_DB_PATH

logger = logging.getLogger("options_agent")


def get_conn():
  Path(OPTIONS_DB_PATH).parent.mkdir(exist_ok=True)
  conn = sqlite3.connect(OPTIONS_DB_PATH)
  conn.row_factory = sqlite3.Row
  conn.execute("PRAGMA journal_mode=WAL")
  return conn


def init_options_db():
  with get_conn() as conn:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS options_signals (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      ts              TEXT NOT NULL,
      underlying      TEXT NOT NULL,
      direction       TEXT NOT NULL,
      confirmations   INTEGER,
      rsi             REAL,
      close_price     REAL,
      reason          TEXT
    );

    CREATE TABLE IF NOT EXISTS options_trades (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      ts              TEXT NOT NULL,
      contract_symbol TEXT NOT NULL,
      underlying      TEXT NOT NULL,
      option_type     TEXT NOT NULL,
      strike          REAL,
      expiration      TEXT,
      action          TEXT NOT NULL,
      contracts       INTEGER,
      premium         REAL,
      amount_usd      REAL,
      mode            TEXT NOT NULL,
      status          TEXT NOT NULL,
      signal_id       INTEGER,
      notes           TEXT,
      strategy_version TEXT
    );

    CREATE TABLE IF NOT EXISTS options_positions (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      contract_symbol TEXT UNIQUE NOT NULL,
      underlying      TEXT NOT NULL,
      option_type     TEXT NOT NULL,
      strike          REAL,
      expiration      TEXT,
      contracts       INTEGER,
      entry_premium   REAL,
      entry_ts        TEXT,
      stop_loss       REAL,
      take_profit     REAL,
      status          TEXT DEFAULT 'OPEN'
    );

    CREATE TABLE IF NOT EXISTS options_pnl (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      contract_symbol TEXT,
      underlying      TEXT,
      option_type     TEXT,
      entry_premium   REAL,
      exit_premium    REAL,
      contracts       INTEGER,
      pnl_usd         REAL,
      pnl_pct         REAL,
      entry_ts        TEXT,
      exit_ts         TEXT
    );

    CREATE TABLE IF NOT EXISTS options_strategy_log (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      ts              TEXT NOT NULL,
      version         TEXT NOT NULL,
      description     TEXT
    );
    """)
    try:
      conn.execute(
        "ALTER TABLE options_positions ADD COLUMN auto_managed INTEGER DEFAULT 1"
      )
    except Exception:
      pass
  cleanup_stale_pending_option_positions()
  logger.info("Options database initialized")


def cleanup_stale_pending_option_positions(max_age_minutes: int = 5):
  cutoff = (datetime.now() - timedelta(minutes=max_age_minutes)).isoformat()
  with get_conn() as conn:
    cur = conn.execute(
      "UPDATE options_positions SET status='FAILED' "
      "WHERE status='PENDING' AND entry_ts < ?",
      (cutoff,),
    )
    if cur.rowcount:
      logger.warning(f"Cleaned up {cur.rowcount} stale PENDING option position(s)")


def log_options_signal(signal) -> int:
  eq = signal.equity_signal
  with get_conn() as conn:
    cur = conn.execute("""
      INSERT INTO options_signals
        (ts, underlying, direction, confirmations, rsi, close_price, reason)
      VALUES (?,?,?,?,?,?,?)
    """, (
      datetime.now().isoformat(), signal.underlying, signal.direction,
      eq.confirmations, eq.rsi, eq.close_price, signal.reason,
    ))
    return cur.lastrowid


def log_options_trade(
    contract_symbol, underlying, option_type, strike, expiration,
    action, contracts, premium, mode, status,
    signal_id=None, notes=None, strategy_version=None,
):
  amount = round(contracts * premium * 100, 2)
  with get_conn() as conn:
    conn.execute("""
      INSERT INTO options_trades
        (ts, contract_symbol, underlying, option_type, strike, expiration,
         action, contracts, premium, amount_usd, mode, status,
         signal_id, notes, strategy_version)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
      datetime.now().isoformat(), contract_symbol, underlying, option_type,
      strike, expiration, action, contracts, premium, amount, mode, status,
      signal_id, notes, strategy_version,
    ))


def open_option_position_pending(
    contract_symbol, underlying, option_type, strike, expiration,
    contracts, entry_premium, stop_loss, take_profit, auto_managed=1,
):
  with get_conn() as conn:
    conn.execute("""
      INSERT OR REPLACE INTO options_positions
        (contract_symbol, underlying, option_type, strike, expiration,
         contracts, entry_premium, entry_ts, stop_loss, take_profit, status,
         auto_managed)
      VALUES (?,?,?,?,?,?,?,?,?,?,'PENDING',?)
    """, (
      contract_symbol, underlying, option_type, strike, expiration,
      contracts, entry_premium, datetime.now().isoformat(), stop_loss, take_profit,
      auto_managed,
    ))


def confirm_option_position(contract_symbol):
  with get_conn() as conn:
    conn.execute(
      "UPDATE options_positions SET status='OPEN' "
      "WHERE contract_symbol=? AND status='PENDING'",
      (contract_symbol,),
    )


def fail_pending_option_position(contract_symbol):
  with get_conn() as conn:
    conn.execute(
      "UPDATE options_positions SET status='FAILED' "
      "WHERE contract_symbol=? AND status='PENDING'",
      (contract_symbol,),
    )


def close_option_position(contract_symbol, exit_premium):
  with get_conn() as conn:
    row = conn.execute(
      "SELECT * FROM options_positions WHERE contract_symbol=? AND status='OPEN'",
      (contract_symbol,),
    ).fetchone()
    if not row:
      return
    contracts = row["contracts"]
    entry = row["entry_premium"]
    pnl_usd = (exit_premium - entry) * contracts * 100
    pnl_pct = ((exit_premium - entry) / entry * 100) if entry else 0
    conn.execute(
      "UPDATE options_positions SET status='CLOSED' WHERE contract_symbol=?",
      (contract_symbol,),
    )
    conn.execute("""
      INSERT INTO options_pnl
        (contract_symbol, underlying, option_type, entry_premium, exit_premium,
         contracts, pnl_usd, pnl_pct, entry_ts, exit_ts)
      VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
      contract_symbol, row["underlying"], row["option_type"],
      entry, exit_premium, contracts, round(pnl_usd, 2), round(pnl_pct, 3),
      row["entry_ts"], datetime.now().isoformat(),
    ))
    logger.info(f"Closed option {contract_symbol} | P&L: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")


def get_open_option_positions() -> list:
  with get_conn() as conn:
    return conn.execute(
      "SELECT * FROM options_positions WHERE status='OPEN'"
    ).fetchall()


def count_active_option_positions() -> int:
  with get_conn() as conn:
    row = conn.execute(
      "SELECT COUNT(*) as n FROM options_positions WHERE status IN ('OPEN','PENDING')"
    ).fetchone()
    return row["n"] or 0


def has_active_underlying(underlying: str) -> bool:
  with get_conn() as conn:
    row = conn.execute(
      "SELECT 1 FROM options_positions WHERE underlying=? "
      "AND status IN ('OPEN','PENDING')",
      (underlying,),
    ).fetchone()
    return row is not None


def was_underlying_recently_closed(underlying: str, hours: int = 24) -> bool:
  cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
  with get_conn() as conn:
    row = conn.execute(
      "SELECT COUNT(*) as n FROM options_pnl WHERE underlying=? AND exit_ts >= ?",
      (underlying, cutoff),
    ).fetchone()
    return (row["n"] or 0) > 0


def get_options_daily_pnl() -> float:
  today = datetime.now().date().isoformat()
  with get_conn() as conn:
    row = conn.execute(
      "SELECT SUM(pnl_usd) as total FROM options_pnl WHERE date(exit_ts)=?",
      (today,),
    ).fetchone()
    return row["total"] or 0.0


def stamp_options_strategy_version(version: str, description: str = ""):
  with get_conn() as conn:
    conn.execute(
      "INSERT INTO options_strategy_log (ts, version, description) VALUES (?,?,?)",
      (datetime.now().isoformat(), version, description),
    )
  logger.info(f"Options strategy version stamped: {version}")


def print_options_summary():
  with get_conn() as conn:
    trades = conn.execute("SELECT COUNT(*) as n FROM options_trades").fetchone()["n"]
    signals = conn.execute(
      "SELECT COUNT(*) as n FROM options_signals WHERE direction != 'NONE'"
    ).fetchone()["n"]
    total_pnl = conn.execute("SELECT SUM(pnl_usd) as t FROM options_pnl").fetchone()["t"] or 0
    wins = conn.execute("SELECT COUNT(*) as n FROM options_pnl WHERE pnl_usd > 0").fetchone()["n"]
    losses = conn.execute("SELECT COUNT(*) as n FROM options_pnl WHERE pnl_usd <= 0").fetchone()["n"]
    open_pos = conn.execute(
      "SELECT COUNT(*) as n FROM options_positions WHERE status='OPEN'"
    ).fetchone()["n"]
  print(f"\n{'='*50}")
  print(f"  OPTIONS TRADING AGENT SUMMARY")
  print(f"{'='*50}")
  print(f"  Actionable Signals : {signals}")
  print(f"  Trades Executed    : {trades}")
  print(f"  Open Positions     : {open_pos}")
  print(f"  Wins / Losses      : {wins} / {losses}")
  print(f"  Total P&L          : ${total_pnl:+.2f}")
  print(f"{'='*50}\n")
