#!/usr/bin/env python3
"""
Backtest Engine
===============
Runs the mean reversion strategy against 6 months of historical data.
Uses the exact same RSI + Bollinger + Z-score signals as the live agent.

Usage:
    python backtest.py

Generates backtest_results.html and opens it in your browser.
Takes about 1-2 minutes to run.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import webbrowser, os, sys

# ── Strategy parameters (must match settings.py) ──────────────────────
TRADE_AMOUNT_USD  = 100.0
STOP_LOSS_PCT     = 0.03
TAKE_PROFIT_PCT   = 0.05
RSI_PERIOD        = 14
RSI_OVERSOLD      = 35
RSI_OVERBOUGHT    = 65
BBAND_PERIOD      = 20
BBAND_STD         = 2.0
ZSCORE_PERIOD     = 20
ZSCORE_THRESHOLD  = 1.5
MIN_SIGNALS       = 2
MAX_OPEN_POSITIONS= 5
MAX_DAY_TRADES    = 3
LOOKBACK_DAYS     = 180   # 6 months

# ── Fixed universe (same stocks the live agent tracks) ─────────────────
SYMBOLS = [
    "AAPL","TSLA","NVDA","AMD","AMZN","MSFT","META","GOOGL","SPY","QQQ",
    "SOFI","PLTR","BAC","F","T","INTC","WFC","C","XOM","JPM",
    "BABA","NIO","UBER","LYFT","RIVN","LCID","GME","AMC","HOOD","SNAP"
]

OUTPUT = "backtest_results.html"


# ── Indicators ─────────────────────────────────────────────────────────

def compute_rsi(prices, period=RSI_PERIOD):
    delta = prices.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    ag    = gain.ewm(com=period-1, min_periods=period).mean()
    al    = loss.ewm(com=period-1, min_periods=period).mean()
    rs    = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def compute_bb(prices, period=BBAND_PERIOD, std=BBAND_STD):
    ma    = prices.rolling(period).mean()
    sd    = prices.rolling(period).std()
    return ma + std*sd, ma, ma - std*sd

def compute_zscore(prices, period=ZSCORE_PERIOD):
    ma  = prices.rolling(period).mean()
    sd  = prices.rolling(period).std()
    return (prices - ma) / sd


# ── Core backtest ──────────────────────────────────────────────────────

def run_backtest():
    end   = datetime.today()
    start = end - timedelta(days=LOOKBACK_DAYS + 60)  # extra for warmup

    print(f"Downloading {len(SYMBOLS)} symbols ({LOOKBACK_DAYS} days)...")
    all_trades  = []
    daily_dt    = {}   # day -> day_trade_count for PDT simulation

    for i, symbol in enumerate(SYMBOLS):
        print(f"  [{i+1}/{len(SYMBOLS)}] {symbol}", end="\r")
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, interval="1d", auto_adjust=True)
            if df.empty or len(df) < BBAND_PERIOD + 10:
                continue
            df = df[["Close"]].dropna()
            prices = df["Close"]

            rsi    = compute_rsi(prices)
            upper, mid, lower = compute_bb(prices)
            zscore = compute_zscore(prices)

            # Only look at dates within backtest window
            backtest_start = end - timedelta(days=LOOKBACK_DAYS)
            dates = prices.index[prices.index >= pd.Timestamp(backtest_start, tz=prices.index.tz)]

            in_trade    = None   # dict with entry info when position open
            for date in dates:
                if date not in prices.index:
                    continue
                idx   = prices.index.get_loc(date)
                if idx < BBAND_PERIOD + 5:
                    continue

                close   = float(prices.iloc[idx])
                r       = float(rsi.iloc[idx])
                up      = float(upper.iloc[idx])
                lo      = float(lower.iloc[idx])
                z       = float(zscore.iloc[idx])

                # ── Check exit if in trade ──
                if in_trade:
                    entry  = in_trade["entry"]
                    action = in_trade["action"]
                    pnl_raw = (close - entry) if action == "BUY" else (entry - close)
                    pnl_pct = pnl_raw / entry

                    hit_stop = pnl_pct <= -STOP_LOSS_PCT
                    hit_take = pnl_pct >= TAKE_PROFIT_PCT
                    days_held = (date - in_trade["entry_date"]).days

                    if hit_stop or hit_take or days_held >= 10:
                        shares  = in_trade["shares"]
                        pnl_usd = round(pnl_raw * shares, 2)
                        exit_reason = "stop_loss" if hit_stop else ("take_profit" if hit_take else "timeout")
                        all_trades.append({
                            "symbol":      symbol,
                            "action":      action,
                            "entry_price": round(entry, 3),
                            "exit_price":  round(close, 3),
                            "shares":      shares,
                            "pnl_usd":     pnl_usd,
                            "pnl_pct":     round(pnl_pct * 100, 2),
                            "entry_date":  in_trade["entry_date"].strftime("%Y-%m-%d"),
                            "exit_date":   date.strftime("%Y-%m-%d"),
                            "days_held":   days_held,
                            "exit_reason": exit_reason,
                            "confirmations": in_trade["confirmations"],
                        })
                        in_trade = None
                    continue  # only 1 position per symbol at a time

                # ── Check entry signals ──
                buy_votes = sell_votes = 0
                if r < RSI_OVERSOLD:   buy_votes  += 1
                elif r > RSI_OVERBOUGHT: sell_votes += 1
                if close <= lo:        buy_votes  += 1
                elif close >= up:      sell_votes += 1
                if z <= -ZSCORE_THRESHOLD:  buy_votes  += 1
                elif z >= ZSCORE_THRESHOLD: sell_votes += 1

                if buy_votes >= MIN_SIGNALS:
                    direction = "BUY"
                    confirms  = buy_votes
                elif sell_votes >= MIN_SIGNALS:
                    direction = "SELL"
                    confirms  = sell_votes
                else:
                    continue

                # PDT check
                day_str = date.strftime("%Y-%m-%d")
                if daily_dt.get(day_str, 0) >= MAX_DAY_TRADES:
                    continue

                shares = max(1, int(TRADE_AMOUNT_USD / close))
                in_trade = {
                    "action":       direction,
                    "entry":        close,
                    "entry_date":   date,
                    "shares":       shares,
                    "confirmations":confirms,
                }

        except Exception as e:
            pass

    print(f"\nBacktest complete. {len(all_trades)} trades simulated.")
    return all_trades


# ── Analytics ──────────────────────────────────────────────────────────

def analyze(trades):
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    total_pnl  = round(df["pnl_usd"].sum(), 2)
    wins       = df[df["pnl_usd"] > 0]
    losses     = df[df["pnl_usd"] <= 0]
    win_rate   = round(len(wins) / len(df) * 100, 1) if len(df) > 0 else 0
    avg_win    = round(wins["pnl_usd"].mean(), 2) if len(wins) > 0 else 0
    avg_loss   = round(losses["pnl_usd"].mean(), 2) if len(losses) > 0 else 0
    avg_hold   = round(df["days_held"].mean(), 1)
    best       = df.loc[df["pnl_usd"].idxmax()]
    worst      = df.loc[df["pnl_usd"].idxmin()]

    # Cumulative P&L by exit date
    df_sorted  = df.sort_values("exit_date")
    df_sorted["cum_pnl"] = df_sorted["pnl_usd"].cumsum()

    # By confirmation count
    by_conf    = df.groupby("confirmations")["pnl_usd"].agg(["count","sum","mean"]).round(2)

    # By exit reason
    by_reason  = df.groupby("exit_reason")["pnl_usd"].agg(["count","sum"]).round(2)

    return {
        "total_pnl":  total_pnl,
        "total_trades": len(df),
        "win_rate":   win_rate,
        "wins":       len(wins),
        "losses":     len(losses),
        "avg_win":    avg_win,
        "avg_loss":   avg_loss,
        "avg_hold":   avg_hold,
        "best_trade": best.to_dict(),
        "worst_trade":worst.to_dict(),
        "cum_pnl":    df_sorted[["exit_date","cum_pnl"]].values.tolist(),
        "by_conf":    by_conf.reset_index().to_dict("records"),
        "by_reason":  by_reason.reset_index().to_dict("records"),
        "trades":     df_sorted.to_dict("records"),
    }


# ── HTML Dashboard ─────────────────────────────────────────────────────

def build_html(stats, trades):
    now  = datetime.now().strftime("%b %d %Y %I:%M %p")
    s    = stats
    pnl_color = "#00c896" if s["total_pnl"] >= 0 else "#ff4d6d"
    pnl_str   = ("+$" if s["total_pnl"] >= 0 else "-$") + str(abs(s["total_pnl"]))

    def badge(action):
        c = "#00c896" if action == "BUY" else "#ff4d6d"
        return f'<span style="background:{c}22;color:{c};padding:2px 7px;border-radius:3px;font-size:11px;font-weight:700">{action}</span>'

    def pspan(val, suffix=""):
        try:
            c = "#00c896" if float(val) >= 0 else "#ff4d6d"
            prefix = "+" if float(val) >= 0 else ""
            return f'<span style="color:{c}">{prefix}{float(val):.2f}{suffix}</span>'
        except:
            return str(val)

    def reason_badge(r):
        colors = {"stop_loss":"#ff4d6d","take_profit":"#00c896","timeout":"#ffd60a"}
        c = colors.get(r, "#888")
        return f'<span style="background:{c}22;color:{c};padding:2px 7px;border-radius:3px;font-size:10px">{r}</span>'

    # Cumulative P&L chart data
    cum_labels = [str(x[0])[:10] for x in s["cum_pnl"]]
    cum_values = [round(x[1], 2) for x in s["cum_pnl"]]
    chart_color = "#00c896" if s["total_pnl"] >= 0 else "#ff4d6d"

    # Trade rows
    trade_rows = ""
    for r in reversed(s["trades"][-50:]):  # last 50
        trade_rows += f"""<tr>
            <td><b>{r["symbol"]}</b></td>
            <td>{badge(r["action"])}</td>
            <td>{r["shares"]}</td>
            <td>${r["entry_price"]}</td>
            <td>${r["exit_price"]}</td>
            <td>{pspan(r["pnl_usd"])}</td>
            <td>{pspan(r["pnl_pct"],"%")}</td>
            <td>{r["days_held"]}d</td>
            <td>{reason_badge(r["exit_reason"])}</td>
            <td>{"★"*r["confirmations"]}{"☆"*(3-r["confirmations"])}</td>
            <td style="color:#888">{r["entry_date"]}</td>
        </tr>"""

    # Confirmation breakdown rows
    conf_rows = ""
    for r in s["by_conf"]:
        conf_rows += f"""<tr>
            <td>{"★"*int(r["confirmations"])}{"☆"*(3-int(r["confirmations"]))} {int(r["confirmations"])}/3</td>
            <td>{int(r["count"])}</td>
            <td>{pspan(r["sum"])}</td>
            <td>{pspan(r["mean"])}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Backtest Results</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0f1e;color:#c8d8f0;font-family:-apple-system,BlinkMacSystemFont,sans-serif}}
.header{{background:#0f1729;border-bottom:1px solid #1e2d4a;padding:20px 32px;display:flex;justify-content:space-between;align-items:center}}
.title{{font-size:20px;font-weight:800;color:#fff}}
.subtitle{{font-size:12px;color:#ffd60a;margin-top:3px}}
.badge{{background:#ffd60a22;color:#ffd60a;border:1px solid #ffd60a44;padding:4px 12px;border-radius:4px;font-size:11px}}
.main{{padding:28px 32px}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px}}
.stats2{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px}}
.card{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:20px}}
.label{{font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px}}
.val{{font-size:26px;font-weight:800}}
.sub{{font-size:11px;color:#4a6080;margin-top:5px}}
.sec{{font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:#4a6080;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e2d4a}}
.tw{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;overflow:hidden;margin-bottom:24px}}
table{{width:100%;border-collapse:collapse}}
th{{font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;padding:10px 14px;text-align:left;background:#162038;font-weight:400}}
td{{font-size:12px;padding:11px 14px;border-bottom:1px solid #1e2d4a33;font-family:Courier,monospace}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#00c89606}}
.chart-wrap{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:24px;margin-bottom:24px}}
.two{{display:grid;grid-template-columns:2fr 1fr;gap:20px;margin-bottom:24px}}
.updated{{font-size:11px;color:#4a6080}}
</style>
</head><body>
<div class="header">
  <div>
    <div class="title">📊 BACKTEST RESULTS</div>
    <div class="subtitle">6-MONTH HISTORICAL SIMULATION · MEAN REVERSION STRATEGY</div>
  </div>
  <div style="display:flex;align-items:center;gap:16px">
    <span class="badge">⚠ PAPER SIMULATION</span>
    <span class="updated">Generated: {now}</span>
  </div>
</div>

<div class="main">

  <!-- Primary stats -->
  <div class="stats">
    <div class="card">
      <div class="label">Total P&amp;L (6mo)</div>
      <div class="val" style="color:{pnl_color}">{pnl_str}</div>
      <div class="sub">{s["total_trades"]} trades simulated</div>
    </div>
    <div class="card">
      <div class="label">Win Rate</div>
      <div class="val" style="color:#00c896">{s["win_rate"]}%</div>
      <div class="sub">{s["wins"]}W / {s["losses"]}L</div>
    </div>
    <div class="card">
      <div class="label">Avg Win</div>
      <div class="val" style="color:#00c896">+${s["avg_win"]}</div>
      <div class="sub">per winning trade</div>
    </div>
    <div class="card">
      <div class="label">Avg Loss</div>
      <div class="val" style="color:#ff4d6d">${s["avg_loss"]}</div>
      <div class="sub">per losing trade</div>
    </div>
  </div>

  <!-- Secondary stats -->
  <div class="stats2">
    <div class="card">
      <div class="label">Avg Hold Time</div>
      <div class="val" style="color:#fff">{s["avg_hold"]}d</div>
      <div class="sub">days per trade</div>
    </div>
    <div class="card">
      <div class="label">Best Trade</div>
      <div class="val" style="color:#00c896">+${s["best_trade"].get("pnl_usd",0)}</div>
      <div class="sub">{s["best_trade"].get("symbol","")} on {s["best_trade"].get("exit_date","")}</div>
    </div>
    <div class="card">
      <div class="label">Worst Trade</div>
      <div class="val" style="color:#ff4d6d">${s["worst_trade"].get("pnl_usd",0)}</div>
      <div class="sub">{s["worst_trade"].get("symbol","")} on {s["worst_trade"].get("exit_date","")}</div>
    </div>
    <div class="card">
      <div class="label">Profit Factor</div>
      <div class="val" style="color:#ffd60a">{round(abs(s["avg_win"] * s["wins"]) / max(abs(s["avg_loss"] * s["losses"]),0.01),2)}x</div>
      <div class="sub">gross wins / gross losses</div>
    </div>
  </div>

  <!-- Cumulative P&L chart -->
  <div class="two">
    <div>
      <div class="sec">Cumulative P&amp;L Over 6 Months</div>
      <div class="chart-wrap">
        <canvas id="pnlChart" height="200"></canvas>
      </div>
    </div>
    <div>
      <div class="sec">Signal Strength Breakdown</div>
      <div class="tw"><table>
        <thead><tr><th>Confirmations</th><th>Trades</th><th>Total P&amp;L</th><th>Avg P&amp;L</th></tr></thead>
        <tbody>{conf_rows}</tbody>
      </table></div>
    </div>
  </div>

  <!-- Trade log -->
  <div class="sec">All Simulated Trades (Last 50)</div>
  <div class="tw"><table>
    <thead><tr>
      <th>Symbol</th><th>Action</th><th>Qty</th><th>Entry</th><th>Exit</th>
      <th>P&amp;L $</th><th>P&amp;L %</th><th>Held</th><th>Exit Reason</th><th>Signals</th><th>Entry Date</th>
    </tr></thead>
    <tbody>{trade_rows}</tbody>
  </table></div>

</div>

<script>
const ctx = document.getElementById('pnlChart').getContext('2d');
const labels = {cum_labels};
const values = {cum_values};
const color  = '{chart_color}';
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: labels,
    datasets: [{{
      label: 'Cumulative P&L ($)',
      data: values,
      borderColor: color,
      backgroundColor: color + '18',
      fill: true,
      tension: 0.3,
      pointRadius: 0,
      borderWidth: 2,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          label: ctx => '$' + ctx.parsed.y.toFixed(2)
        }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: '#4a6080', maxTicksLimit: 8, font: {{size:10}} }},
        grid: {{ color: '#1e2d4a' }}
      }},
      y: {{
        ticks: {{ color: '#4a6080', callback: v => '$'+v, font: {{size:10}} }},
        grid: {{ color: '#1e2d4a' }}
      }}
    }}
  }}
}});
</script>
</body></html>"""
    return html


# ── Main ───────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*55)
    print("  BACKTEST ENGINE — 6 Month Simulation")
    print("  Strategy: Mean Reversion (RSI + BB + Z-score)")
    print("  Universe: 30 most-active stocks")
    print("="*55 + "\n")

    trades = run_backtest()

    if not trades:
        print("No trades generated. Check your internet connection.")
        return

    print("Analyzing results...")
    stats = analyze(trades)

    print(f"\n{'='*40}")
    print(f"  Total P&L    : ${stats['total_pnl']:+.2f}")
    print(f"  Win Rate     : {stats['win_rate']}%")
    print(f"  Total Trades : {stats['total_trades']}")
    print(f"  Avg Win      : +${stats['avg_win']}")
    print(f"  Avg Loss     : ${stats['avg_loss']}")
    print(f"  Avg Hold     : {stats['avg_hold']} days")
    print(f"{'='*40}\n")

    print("Building dashboard...")
    html = build_html(stats, trades)
    Path(OUTPUT).write_text(html)
    print(f"Saved to: {OUTPUT}")
    print("Opening in browser...")
    webbrowser.open("file://" + os.path.abspath(OUTPUT))


if __name__ == "__main__":
    main()
