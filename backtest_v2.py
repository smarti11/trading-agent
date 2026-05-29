#!/usr/bin/env python3
"""
Backtest Engine V2 - Optimized Strategy
========================================
Changes vs V1:
  1. Excludes 3/3 signals (only trades 2/3 confirmations)
  2. Tighter RSI thresholds: 30 oversold / 70 overbought
  3. Tighter stop loss: 2% (was 3%)
  4. Volume filter: only trades when volume > 20-day avg volume

Usage:
    python backtest_v2.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import webbrowser, os

# ── V1 Original params ─────────────────────────────────────────────────
V1 = dict(
    RSI_OVERSOLD=35, RSI_OVERBOUGHT=65,
    STOP_LOSS_PCT=0.03, TAKE_PROFIT_PCT=0.05,
    MIN_SIGNALS=2, MAX_SIGNALS=3,
    VOLUME_FILTER=False,
)

# ── V2 Optimized params ────────────────────────────────────────────────
V2 = dict(
    RSI_OVERSOLD=30, RSI_OVERBOUGHT=70,
    STOP_LOSS_PCT=0.02, TAKE_PROFIT_PCT=0.05,
    MIN_SIGNALS=2, MAX_SIGNALS=2,   # excludes 3/3
    VOLUME_FILTER=True,
)

# ── Shared params ──────────────────────────────────────────────────────
TRADE_AMOUNT_USD  = 100.0
RSI_PERIOD        = 14
BBAND_PERIOD      = 20
BBAND_STD         = 2.0
ZSCORE_PERIOD     = 20
ZSCORE_THRESHOLD  = 1.5
MAX_OPEN_POSITIONS= 5
VOLUME_PERIOD     = 20
LOOKBACK_DAYS     = 180

SYMBOLS = [
    "AAPL","TSLA","NVDA","AMD","AMZN","MSFT","META","GOOGL","SPY","QQQ",
    "SOFI","PLTR","BAC","F","T","INTC","WFC","C","XOM","JPM",
    "BABA","NIO","UBER","LYFT","RIVN","LCID","GME","AMC","HOOD","SNAP"
]

OUTPUT = "backtest_comparison.html"


# ── Indicators ─────────────────────────────────────────────────────────

def compute_rsi(prices):
    delta = prices.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    ag    = gain.ewm(com=RSI_PERIOD-1, min_periods=RSI_PERIOD).mean()
    al    = loss.ewm(com=RSI_PERIOD-1, min_periods=RSI_PERIOD).mean()
    rs    = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def compute_bb(prices):
    ma = prices.rolling(BBAND_PERIOD).mean()
    sd = prices.rolling(BBAND_PERIOD).std()
    return ma + BBAND_STD*sd, ma - BBAND_STD*sd

def compute_zscore(prices):
    ma = prices.rolling(ZSCORE_PERIOD).mean()
    sd = prices.rolling(ZSCORE_PERIOD).std()
    return (prices - ma) / sd

def compute_vol_ratio(volume):
    avg = volume.rolling(VOLUME_PERIOD).mean()
    return volume / avg


# ── Core backtest ──────────────────────────────────────────────────────

def run_backtest(params, label=""):
    end   = datetime.today()
    start = end - timedelta(days=LOOKBACK_DAYS + 60)
    all_trades = []

    print(f"\nRunning {label} ({LOOKBACK_DAYS} days)...")
    for i, symbol in enumerate(SYMBOLS):
        print(f"  [{i+1}/{len(SYMBOLS)}] {symbol}    ", end="\r")
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, interval="1d", auto_adjust=True)
            if df.empty or len(df) < BBAND_PERIOD + 10:
                continue

            prices  = df["Close"].dropna()
            volumes = df["Volume"].dropna()

            rsi      = compute_rsi(prices)
            upper, lower = compute_bb(prices)
            zscore   = compute_zscore(prices)
            vol_ratio= compute_vol_ratio(volumes)

            backtest_start = end - timedelta(days=LOOKBACK_DAYS)
            dates = prices.index[prices.index >= pd.Timestamp(backtest_start, tz=prices.index.tz)]

            in_trade = None
            for date in dates:
                if date not in prices.index:
                    continue
                idx = prices.index.get_loc(date)
                if idx < BBAND_PERIOD + 5:
                    continue

                close = float(prices.iloc[idx])
                r     = float(rsi.iloc[idx])
                up    = float(upper.iloc[idx])
                lo    = float(lower.iloc[idx])
                z     = float(zscore.iloc[idx])
                vr    = float(vol_ratio.iloc[idx]) if idx < len(vol_ratio) else 1.0

                # ── Exit check ──
                if in_trade:
                    entry  = in_trade["entry"]
                    action = in_trade["action"]
                    pnl_raw = (close - entry) if action == "BUY" else (entry - close)
                    pnl_pct = pnl_raw / entry
                    days_held = (date - in_trade["entry_date"]).days

                    if pnl_pct <= -params["STOP_LOSS_PCT"] or pnl_pct >= params["TAKE_PROFIT_PCT"] or days_held >= 10:
                        shares  = in_trade["shares"]
                        pnl_usd = round(pnl_raw * shares, 2)
                        exit_r  = "stop_loss" if pnl_pct <= -params["STOP_LOSS_PCT"] else ("take_profit" if pnl_pct >= params["TAKE_PROFIT_PCT"] else "timeout")
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
                            "exit_reason": exit_r,
                            "confirmations": in_trade["confirmations"],
                        })
                        in_trade = None
                    continue

                # ── Volume filter ──
                if params["VOLUME_FILTER"] and vr < 1.2:
                    continue  # skip low-volume days

                # ── Signal check ──
                buy_votes = sell_votes = 0
                if r < params["RSI_OVERSOLD"]:    buy_votes  += 1
                elif r > params["RSI_OVERBOUGHT"]: sell_votes += 1
                if close <= lo:  buy_votes  += 1
                elif close >= up: sell_votes += 1
                if z <= -ZSCORE_THRESHOLD:  buy_votes  += 1
                elif z >= ZSCORE_THRESHOLD: sell_votes += 1

                if buy_votes == params["MIN_SIGNALS"] and buy_votes <= params["MAX_SIGNALS"]:
                    direction, confirms = "BUY", buy_votes
                elif sell_votes == params["MIN_SIGNALS"] and sell_votes <= params["MAX_SIGNALS"]:
                    direction, confirms = "SELL", sell_votes
                else:
                    continue

                shares = max(1, int(TRADE_AMOUNT_USD / close))
                in_trade = {
                    "action": direction, "entry": close,
                    "entry_date": date, "shares": shares, "confirmations": confirms,
                }

        except Exception:
            pass

    print(f"\n  {label} complete: {len(all_trades)} trades")
    return all_trades


# ── Analytics ──────────────────────────────────────────────────────────

def analyze(trades):
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    total_pnl = round(df["pnl_usd"].sum(), 2)
    wins      = df[df["pnl_usd"] > 0]
    losses    = df[df["pnl_usd"] <= 0]
    closed    = len(df)
    win_rate  = round(len(wins) / closed * 100, 1) if closed > 0 else 0
    avg_win   = round(wins["pnl_usd"].mean(), 2) if len(wins) > 0 else 0
    avg_loss  = round(losses["pnl_usd"].mean(), 2) if len(losses) > 0 else 0
    avg_hold  = round(df["days_held"].mean(), 1)
    best      = df.loc[df["pnl_usd"].idxmax()].to_dict()
    worst     = df.loc[df["pnl_usd"].idxmin()].to_dict()
    gross_win = abs(avg_win * len(wins))
    gross_loss= abs(avg_loss * len(losses))
    pf        = round(gross_win / max(gross_loss, 0.01), 2)
    df_sorted = df.sort_values("exit_date")
    df_sorted["cum_pnl"] = df_sorted["pnl_usd"].cumsum()
    by_reason = df.groupby("exit_reason")["pnl_usd"].agg(["count","sum"]).round(2)
    return {
        "total_pnl": total_pnl, "total_trades": closed,
        "win_rate": win_rate, "wins": len(wins), "losses": len(losses),
        "avg_win": avg_win, "avg_loss": avg_loss, "avg_hold": avg_hold,
        "profit_factor": pf,
        "best_trade": best, "worst_trade": worst,
        "cum_pnl": df_sorted[["exit_date","cum_pnl"]].values.tolist(),
        "by_reason": by_reason.reset_index().to_dict("records"),
        "trades": df_sorted.to_dict("records"),
    }


# ── HTML ───────────────────────────────────────────────────────────────

def build_html(s1, s2):
    now = datetime.now().strftime("%b %d %Y %I:%M %p")

    def color(val):
        return "#00c896" if float(val) >= 0 else "#ff4d6d"

    def fmt(val, prefix="$"):
        v = float(val)
        return ("+$" if v >= 0 else "-$") + str(abs(round(v, 2)))

    def pspan(val, suffix=""):
        c = color(val)
        v = float(val)
        return f'<span style="color:{c}">{("+" if v>=0 else "")}{v:.2f}{suffix}</span>'

    def badge(action):
        c = "#00c896" if action == "BUY" else "#ff4d6d"
        return f'<span style="background:{c}22;color:{c};padding:2px 7px;border-radius:3px;font-size:11px;font-weight:700">{action}</span>'

    def reason_badge(r):
        colors = {"stop_loss":"#ff4d6d","take_profit":"#00c896","timeout":"#ffd60a"}
        c = colors.get(r,"#888")
        return f'<span style="background:{c}22;color:{c};padding:2px 7px;border-radius:3px;font-size:10px">{r}</span>'

    def delta(v1, v2, higher_is_better=True):
        diff = float(v2) - float(v1)
        good = diff > 0 if higher_is_better else diff < 0
        c    = "#00c896" if good else "#ff4d6d"
        sign = "▲" if diff > 0 else "▼"
        return f'<span style="color:{c};font-size:11px">{sign} {abs(diff):.2f}</span>'

    # Charts
    def chart_data(s):
        labels = [str(x[0])[:10] for x in s["cum_pnl"]]
        values = [round(x[1],2) for x in s["cum_pnl"]]
        return labels, values

    l1, v1 = chart_data(s1)
    l2, v2 = chart_data(s2)

    # Trade rows V2
    trade_rows = ""
    for r in reversed(s2["trades"][-50:]):
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
            <td style="color:#888">{r["entry_date"]}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Backtest Comparison</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0f1e;color:#c8d8f0;font-family:-apple-system,BlinkMacSystemFont,sans-serif}}
.header{{background:#0f1729;border-bottom:1px solid #1e2d4a;padding:20px 32px;display:flex;justify-content:space-between;align-items:center}}
.title{{font-size:20px;font-weight:800;color:#fff}}
.subtitle{{font-size:12px;color:#ffd60a;margin-top:3px}}
.main{{padding:28px 32px}}
.compare{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:28px}}
.panel{{background:#0f1729;border:1px solid #1e2d4a;border-radius:12px;padding:24px}}
.panel.v2{{border-color:#00c896;box-shadow:0 0 20px rgba(0,200,150,0.08)}}
.panel-title{{font-size:13px;font-weight:700;margin-bottom:4px}}
.panel-sub{{font-size:11px;color:#4a6080;margin-bottom:20px}}
.metrics{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.metric{{background:#162038;border-radius:8px;padding:14px}}
.metric-label{{font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px}}
.metric-val{{font-size:20px;font-weight:800}}
.metric-sub{{font-size:10px;color:#4a6080;margin-top:4px}}
.verdict{{background:#00c89611;border:1px solid #00c89644;border-radius:10px;padding:20px;margin-bottom:28px;display:flex;gap:20px;align-items:center}}
.verdict-icon{{font-size:36px}}
.verdict-title{{font-size:15px;font-weight:700;color:#00c896;margin-bottom:4px}}
.verdict-text{{font-size:13px;color:#c8d8f0;line-height:1.6}}
.sec{{font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:#4a6080;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e2d4a}}
.chart-wrap{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:24px;margin-bottom:24px}}
.tw{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;overflow:hidden;margin-bottom:24px}}
table{{width:100%;border-collapse:collapse}}
th{{font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;padding:10px 14px;text-align:left;background:#162038;font-weight:400}}
td{{font-size:12px;padding:11px 14px;border-bottom:1px solid #1e2d4a33;font-family:Courier,monospace}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#00c89606}}
.tag{{display:inline-block;font-size:10px;padding:2px 8px;border-radius:3px;margin-right:4px;margin-bottom:4px}}
.tag-new{{background:#00c89622;color:#00c896}}
</style>
</head><body>

<div class="header">
  <div>
    <div class="title">📊 STRATEGY COMPARISON — V1 vs V2</div>
    <div class="subtitle">6-MONTH BACKTEST · MEAN REVERSION · 4 OPTIMIZATIONS APPLIED</div>
  </div>
  <span style="font-size:11px;color:#4a6080">Generated: {now}</span>
</div>

<div class="main">

  <!-- Verdict -->
  <div class="verdict">
    <div class="verdict-icon">{'✅' if s2["total_pnl"] > s1["total_pnl"] else '⚠️'}</div>
    <div>
      <div class="verdict-title">{'V2 Outperforms V1' if s2["total_pnl"] > s1["total_pnl"] else 'V1 Still Leads — Further Tuning Needed'}</div>
      <div class="verdict-text">
        V1 (original): <b>{fmt(s1["total_pnl"])}</b> profit, <b>{s1["win_rate"]}%</b> win rate, <b>{s1["total_trades"]}</b> trades &nbsp;|&nbsp;
        V2 (optimized): <b>{fmt(s2["total_pnl"])}</b> profit, <b>{s2["win_rate"]}%</b> win rate, <b>{s2["total_trades"]}</b> trades<br>
        Changes applied: <span class="tag tag-new">RSI 30/70</span><span class="tag tag-new">Stop 2%</span><span class="tag tag-new">Exclude 3/3</span><span class="tag tag-new">Volume Filter</span>
      </div>
    </div>
  </div>

  <!-- Side by side -->
  <div class="compare">
    <div class="panel">
      <div class="panel-title" style="color:#ffd60a">V1 — Original Strategy</div>
      <div class="panel-sub">RSI 35/65 · Stop 3% · All signals · No volume filter</div>
      <div class="metrics">
        <div class="metric"><div class="metric-label">Total P&L</div><div class="metric-val" style="color:{color(s1["total_pnl"])}">{fmt(s1["total_pnl"])}</div></div>
        <div class="metric"><div class="metric-label">Win Rate</div><div class="metric-val" style="color:#00c896">{s1["win_rate"]}%</div></div>
        <div class="metric"><div class="metric-label">Avg Win</div><div class="metric-val" style="color:#00c896">+${s1["avg_win"]}</div></div>
        <div class="metric"><div class="metric-label">Avg Loss</div><div class="metric-val" style="color:#ff4d6d">${s1["avg_loss"]}</div></div>
        <div class="metric"><div class="metric-label">Trades</div><div class="metric-val" style="color:#fff">{s1["total_trades"]}</div></div>
        <div class="metric"><div class="metric-label">Profit Factor</div><div class="metric-val" style="color:#ffd60a">{s1["profit_factor"]}x</div></div>
        <div class="metric"><div class="metric-label">Best Trade</div><div class="metric-val" style="color:#00c896;font-size:14px">+${s1["best_trade"]["pnl_usd"]}<br><span style="font-size:10px;color:#4a6080">{s1["best_trade"]["symbol"]}</span></div></div>
        <div class="metric"><div class="metric-label">Worst Trade</div><div class="metric-val" style="color:#ff4d6d;font-size:14px">${s1["worst_trade"]["pnl_usd"]}<br><span style="font-size:10px;color:#4a6080">{s1["worst_trade"]["symbol"]}</span></div></div>
      </div>
    </div>

    <div class="panel v2">
      <div class="panel-title" style="color:#00c896">V2 — Optimized Strategy</div>
      <div class="panel-sub">RSI 30/70 · Stop 2% · 2/3 only · Volume filter ≥1.2x avg</div>
      <div class="metrics">
        <div class="metric"><div class="metric-label">Total P&L</div><div class="metric-val" style="color:{color(s2["total_pnl"])}">{fmt(s2["total_pnl"])} {delta(s1["total_pnl"],s2["total_pnl"])}</div></div>
        <div class="metric"><div class="metric-label">Win Rate</div><div class="metric-val" style="color:#00c896">{s2["win_rate"]}% {delta(s1["win_rate"],s2["win_rate"])}</div></div>
        <div class="metric"><div class="metric-label">Avg Win</div><div class="metric-val" style="color:#00c896">+${s2["avg_win"]} {delta(s1["avg_win"],s2["avg_win"])}</div></div>
        <div class="metric"><div class="metric-label">Avg Loss</div><div class="metric-val" style="color:#ff4d6d">${s2["avg_loss"]} {delta(s1["avg_loss"],s2["avg_loss"],higher_is_better=False)}</div></div>
        <div class="metric"><div class="metric-label">Trades</div><div class="metric-val" style="color:#fff">{s2["total_trades"]}</div></div>
        <div class="metric"><div class="metric-label">Profit Factor</div><div class="metric-val" style="color:#ffd60a">{s2["profit_factor"]}x {delta(s1["profit_factor"],s2["profit_factor"])}</div></div>
        <div class="metric"><div class="metric-label">Best Trade</div><div class="metric-val" style="color:#00c896;font-size:14px">+${s2["best_trade"]["pnl_usd"]}<br><span style="font-size:10px;color:#4a6080">{s2["best_trade"]["symbol"]}</span></div></div>
        <div class="metric"><div class="metric-label">Worst Trade</div><div class="metric-val" style="color:#ff4d6d;font-size:14px">${s2["worst_trade"]["pnl_usd"]}<br><span style="font-size:10px;color:#4a6080">{s2["worst_trade"]["symbol"]}</span></div></div>
      </div>
    </div>
  </div>

  <!-- Chart -->
  <div class="sec">Cumulative P&L — V1 vs V2 Over 6 Months</div>
  <div class="chart-wrap">
    <canvas id="chart" height="120"></canvas>
  </div>

  <!-- V2 Trade log -->
  <div class="sec">V2 Optimized — All Simulated Trades (Last 50)</div>
  <div class="tw"><table>
    <thead><tr><th>Symbol</th><th>Action</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&L $</th><th>P&L %</th><th>Held</th><th>Exit Reason</th><th>Entry Date</th></tr></thead>
    <tbody>{trade_rows}</tbody>
  </table></div>

</div>

<script>
const ctx = document.getElementById('chart').getContext('2d');
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: {l2},
    datasets: [
      {{
        label: 'V1 Original',
        data: {v1},
        borderColor: '#ffd60a',
        backgroundColor: 'transparent',
        tension: 0.3, pointRadius: 0, borderWidth: 1.5, borderDash: [4,3]
      }},
      {{
        label: 'V2 Optimized',
        data: {v2},
        borderColor: '#00c896',
        backgroundColor: 'rgba(0,200,150,0.08)',
        fill: true,
        tension: 0.3, pointRadius: 0, borderWidth: 2
      }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ labels: {{ color: '#4a6080', font: {{size:11}} }} }},
      tooltip: {{ callbacks: {{ label: c => c.dataset.label + ': $' + c.parsed.y.toFixed(2) }} }}
    }},
    scales: {{
      x: {{ ticks: {{ color:'#4a6080', maxTicksLimit:8, font:{{size:10}} }}, grid: {{ color:'#1e2d4a' }} }},
      y: {{ ticks: {{ color:'#4a6080', callback: v=>'$'+v, font:{{size:10}} }}, grid: {{ color:'#1e2d4a' }} }}
    }}
  }}
}});
</script>
</body></html>"""
    return html


def main():
    print("\n" + "="*55)
    print("  STRATEGY COMPARISON BACKTEST")
    print("  V1 Original vs V2 Optimized (4 changes)")
    print("="*55)

    trades_v1 = run_backtest(V1, "V1 Original")
    trades_v2 = run_backtest(V2, "V2 Optimized")

    print("\nAnalyzing...")
    s1 = analyze(trades_v1)
    s2 = analyze(trades_v2)

    print(f"\n{'='*45}")
    print(f"{'Metric':<20} {'V1':>10} {'V2':>10} {'Delta':>10}")
    print(f"{'-'*45}")
    print(f"{'Total P&L':<20} ${s1['total_pnl']:>9} ${s2['total_pnl']:>9} {'+' if s2['total_pnl']>s1['total_pnl'] else ''}{s2['total_pnl']-s1['total_pnl']:>9.2f}")
    print(f"{'Win Rate':<20} {s1['win_rate']:>9}% {s2['win_rate']:>9}%")
    print(f"{'Total Trades':<20} {s1['total_trades']:>10} {s2['total_trades']:>10}")
    print(f"{'Avg Win':<20} ${s1['avg_win']:>9} ${s2['avg_win']:>9}")
    print(f"{'Avg Loss':<20} ${s1['avg_loss']:>9} ${s2['avg_loss']:>9}")
    print(f"{'Profit Factor':<20} {s1['profit_factor']:>9}x {s2['profit_factor']:>9}x")
    print(f"{'='*45}")

    print("\nBuilding comparison dashboard...")
    html = build_html(s1, s2)
    Path(OUTPUT).write_text(html)
    print(f"Saved to: {OUTPUT}")
    webbrowser.open("file://" + os.path.abspath(OUTPUT))

if __name__ == "__main__":
    main()
