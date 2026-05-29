# ============================================================
# Trading Agent Configuration
# ============================================================
# Set PAPER_TRADING = True to run in paper mode (no real orders)
# Set PAPER_TRADING = False only when you're ready to go live
# ============================================================

PAPER_TRADING = True  # <-- START HERE. Flip to False for live.

# --- E*Trade API Credentials ---
# Get these from: https://developer.etrade.com/getting-started
ETRADE_CONSUMER_KEY    = "YOUR_CONSUMER_KEY"
ETRADE_CONSUMER_SECRET = "YOUR_CONSUMER_SECRET"
# Sandbox credentials (separate keys from E*Trade dev portal)
ETRADE_SANDBOX_KEY     = "60852934b24a76cb7c8a9f4e76dfd08f"
ETRADE_SANDBOX_SECRET  = "f2afe8b5e3d5256b6f8e94168b44cc4c120173b86677c3e91ea1de877293a6de"

# --- Trade Sizing ---
TRADE_AMOUNT_USD = 100.00       # Fixed dollar amount per trade
MAX_OPEN_POSITIONS = 5          # Max concurrent positions
MAX_POSITION_PER_SYMBOL = 1     # Only 1 position per symbol at a time

# --- Signal Engine Thresholds ---
RSI_PERIOD        = 14
RSI_OVERSOLD      = 35          # Buy signal threshold
RSI_OVERBOUGHT    = 65          # Sell signal threshold
BBAND_PERIOD      = 20
BBAND_STD         = 2.0         # Standard deviations for bands
ZSCORE_PERIOD     = 20
ZSCORE_THRESHOLD  = 1.5         # Z-score magnitude to trigger
MIN_SIGNALS       = 2           # Min confirmations required (out of 3)

# --- Universe ---
TOP_ACTIVE_COUNT  = 30          # How many most-active stocks to scan
SCAN_INTERVAL_SEC = 300         # How often to scan (seconds) - 5 min

# --- Risk Management ---
STOP_LOSS_PCT     = 0.03        # 3% — reference only, stop-loss exits removed in v3.0
TAKE_PROFIT_PCT   = 0.05        # 5% take profit
MAX_DAILY_LOSS_USD = 300        # Agent pauses if daily loss hits this

# --- v3.0 Exit Controls ---
PREOPEN_GAP_PCT    = 0.06       # Queue close premarket if gap > 6% against position
EMERGENCY_FLOOR_PCT = 0.10      # Emergency exit at 10% adverse move (hard floor)
AGGREGATE_CB_USD   = 30.0       # Circuit breaker: total unrealized loss threshold

# --- Pattern Day Trader (PDT) Rules ---
# Applies when account balance is under $25,000
PDT_PROTECTION    = True        # Set False only if account > $25,000
MAX_DAY_TRADES    = 3           # Max day trades per 5 rolling business days
MIN_HOLD_HOURS    = 4           # Minimum hours to hold before closing same day
MAX_HOLD_DAYS     = 3           # Force-close any position held longer than this (calendar days)
MARKET_OPEN       = "09:30"     # Market open (Eastern)
MARKET_CLOSE      = "16:00"     # Market close (Eastern)
NO_NEW_TRADES_AFTER = "15:30"   # Stop opening new positions after this time

# --- ATR (Average True Range) Filter ---
ATR_PERIOD          = 14        # ATR calculation period
ATR_VOLATILITY_MAX  = 0.05      # Skip if ATR/price > 5% (too volatile/whipsaw)
ATR_VOLATILITY_MIN  = 0.003     # Skip if ATR/price < 0.3% (too thin)
ATR_STOP_MULTIPLIER = 1.5       # Dynamic stop = 1.5x ATR (used when going live)
ATR_TAKE_MULTIPLIER = 2.5       # Dynamic take = 2.5x ATR (used when going live)

# --- Earnings Blackout ---
EARNINGS_BLACKOUT_DAYS = 5      # Block trades within this many days of earnings

# --- Paths ---
DB_PATH           = "db/trades.db"
LOG_PATH          = "logs/agent.log"
