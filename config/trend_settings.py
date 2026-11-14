"""
SPY 200-day trend agent settings.

Rule: hold TREND_SYMBOL while it is above its MA_DAYS simple moving average,
otherwise hold CASH_SYMBOL (a T-bill ETF). Checked once a day near the close.

Backtest 2007-2026 (no band, decide at the close): 9.0% CAGR, -20.5% max
drawdown, vs buy-and-hold SPY 10.8% CAGR, -55.2% max drawdown.
"""

TREND_SYMBOL = "SPY"
CASH_SYMBOL = "SGOV"          # iShares 0-3 Month Treasury Bond ETF
MA_DAYS = 200

# Optional buffer to cut whipsaw: switch to SPY only when price > MA*(1+BAND),
# to cash only when price < MA*(1-BAND). 0.0 = the backtested rule.
BAND_PCT = 0.0

# Paper account starting value. Live mode uses the real account instead.
START_CAPITAL_USD = 10_000.0

DB_PATH = "db/trend.db"
LOG_PATH = "logs/trend_agent.log"
