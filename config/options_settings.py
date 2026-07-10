# ============================================================
# Options Trading Agent Configuration
# ============================================================
# Directional long-options strategy: buy calls on oversold
# mean-reversion signals, buy puts on overbought signals.
# Separate from equity agent — does not affect PATH_C lock.
# ============================================================

from config.settings import PAPER_TRADING, SCAN_INTERVAL_SEC, TOP_ACTIVE_COUNT

# Re-export shared gates
OPTIONS_PAPER_TRADING = PAPER_TRADING
OPTIONS_SCAN_INTERVAL_SEC = SCAN_INTERVAL_SEC
OPTIONS_UNIVERSE_SIZE = TOP_ACTIVE_COUNT

# --- Trade Sizing ---
OPTIONS_TRADE_AMOUNT_USD = 500.00   # Max premium budget per trade
MAX_OPTIONS_POSITIONS = 3           # Max concurrent option positions
MAX_POSITIONS_PER_UNDERLYING = 1    # One option position per underlying

# --- Contract Selection ---
MIN_DTE = 21                        # Skip expirations closer than this
TARGET_DTE = 35                     # Prefer expirations near this
MAX_DTE = 60                        # Skip expirations farther than this
MIN_DELTA = 0.30                    # Minimum absolute delta for strike pick
MAX_DELTA = 0.55                    # Maximum absolute delta for strike pick
MAX_BID_ASK_SPREAD_PCT = 0.15       # Skip if (ask-bid)/mid > 15%
MIN_OPEN_INTEREST = 50              # Liquidity filter
MIN_VOLUME = 10                     # Liquidity filter

# --- Exit Rules (premium-based) ---
STOP_LOSS_PREMIUM_PCT = 0.50        # Exit if premium falls 50% from entry
TAKE_PROFIT_PREMIUM_PCT = 1.00      # Exit if premium doubles
FORCE_CLOSE_DTE = 7                 # Close positions within 7 DTE
MAX_HOLD_DAYS = 21                  # Calendar-day max hold
EMERGENCY_FLOOR_PREMIUM_PCT = 0.70  # Hard exit at 70% premium loss

# --- Risk Limits ---
MAX_DAILY_LOSS_USD = 200.0          # Pause new entries after daily loss
AGGREGATE_CB_USD = 150.0            # Circuit breaker on unrealized loss
NO_NEW_TRADES_AFTER = "15:30"       # Eastern — avoid late-day entries

# --- Strategy ---
ALLOW_PUTS = True                   # Buy puts on SELL signals
ALLOW_CALLS = True                  # Buy calls on BUY signals
REQUIRE_MARKET_TREND = True         # Respect BULL/BEAR trend filter

# --- Paths ---
OPTIONS_DB_PATH = "db/options_trades.db"
OPTIONS_LOG_PATH = "logs/options_agent.log"

# --- Dashboard HTTP server ---
# Default 9080+ avoids conflicts with racing (8081), insider (8083), equity (8080).
OPTIONS_DASHBOARD_PORT_START = 9080
OPTIONS_DASHBOARD_PORT_END = 9099
