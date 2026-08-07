# ============================================================
# Options Trading Agent Configuration — v0.2 trend-dip
# ============================================================
# Strategy: BULL-only long calls on dip-and-reclaim (not raw oversold).
# Does not affect equity PATH_C lock.
# ============================================================

from config.settings import PAPER_TRADING, SCAN_INTERVAL_SEC, TOP_ACTIVE_COUNT

# Re-export shared gates
OPTIONS_PAPER_TRADING = PAPER_TRADING
OPTIONS_SCAN_INTERVAL_SEC = SCAN_INTERVAL_SEC
OPTIONS_UNIVERSE_SIZE = TOP_ACTIVE_COUNT

# --- Trade Sizing (risk-based, not lottery tickets) ---
OPTIONS_TRADE_AMOUNT_USD = 500.00   # Hard cap on premium spend (secondary)
MAX_RISK_USD = 150.00               # Max $ at risk to stop per trade
MAX_CONTRACTS = 3                   # Cap contracts — no 18x cheap options
MIN_UNDERLYING_PRICE = 15.0         # Skip cheap/lottery underlyings
MAX_OPTIONS_POSITIONS = 3
MAX_POSITIONS_PER_UNDERLYING = 1

# --- Contract Selection ---
MIN_DTE = 30                        # Enter with enough time
TARGET_DTE = 37
MAX_DTE = 45
MIN_DELTA = 0.45                    # Prefer higher-delta / less lottery
MAX_DELTA = 0.60
MAX_BID_ASK_SPREAD_PCT = 0.08       # Tighter liquidity
MIN_OPEN_INTEREST = 200
MIN_VOLUME = 50
MIN_PREMIUM = 1.00                  # No sub-$1 lottery premiums

# --- Exit Rules (premium-based) ---
STOP_LOSS_PREMIUM_PCT = 0.35        # Exit if premium falls 35%
TAKE_PROFIT_PREMIUM_PCT = 0.70      # Exit if premium up 70%
TRAIL_ACTIVATE_PCT = 0.40           # After +40%, trail stop up
TRAIL_GIVEBACK_PCT = 0.20           # Give back 20% from peak once trailing
FORCE_CLOSE_DTE = 14                # Close before late theta crush
MAX_HOLD_DAYS = 10                  # Calendar-day max hold
TIME_STOP_DAYS = 5                  # Flat if not +TIME_STOP_MIN_GAIN by then
TIME_STOP_MIN_GAIN_PCT = 0.20       # Need +20% by day 5 or exit
EMERGENCY_FLOOR_PREMIUM_PCT = 0.55  # Hard exit at 55% premium loss

# --- Risk Limits ---
MAX_DAILY_LOSS_USD = 200.0
AGGREGATE_CB_USD = 150.0
NO_NEW_TRADES_AFTER = "15:30"

# --- Strategy: trend-dip reclaim (calls only) ---
ALLOW_PUTS = False                  # Freeze puts until call edge proven
ALLOW_CALLS = True
REQUIRE_BULL_ONLY = True            # No CHOP / BEAR entries
REQUIRE_MARKET_TREND = True         # kept for compatibility

# Dip / reclaim thresholds
MA_PERIOD = 20
DIP_RSI_LOOKBACK = 5                # RSI was below DIP_RSI_MAX in last N days
DIP_RSI_MAX = 40.0
RECLAIM_RSI = 45.0                  # RSI back above this = reclaim
RSI_PERIOD = 14

# --- Paths ---
OPTIONS_DB_PATH = "db/options_trades.db"
OPTIONS_LOG_PATH = "logs/options_agent.log"

# --- Dashboard HTTP server ---
OPTIONS_DASHBOARD_PORT_START = 9080
OPTIONS_DASHBOARD_PORT_END = 9099
