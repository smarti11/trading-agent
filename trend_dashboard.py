"""
SPY Trend Agent Dashboard
=========================
Builds trend_dashboard.html (and options_dashboard.html, so the old bookmark
keeps working) from db/trend.db plus live SPY prices. Rebuilt every 5 min by
regen_watcher.py and right after each trend_agent.py run.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import yfinance as yf

from config.settings import PAPER_TRADING
from config.trend_settings import (
    TREND_SYMBOL, CASH_SYMBOL, MA_DAYS, START_CAPITAL_USD, DB_PATH,
)

OUTPUTS = ["trend_dashboard.html", "options_dashboard.html"]
GREEN, RED, BLUE, MUTED = "#00c896", "#ff4d6d", "#5aa9ff", "#4a6080"


def money(v: float, signed: bool = False) -> str:
    if signed:
        return ("+" if v >= 0 else "-") + f"${abs(v):,.2f}"
    return f"${v:,.2f}"


def pct(v: float) -> str:
    v = 0.0 if abs(v) < 0.005 else v
    return f"{v:+.2f}%"


def load_db():
    if not Path(DB_PATH).exists():
        return None, [], []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    acct = conn.execute("SELECT cash, symbol, shares FROM account WHERE id = 1").fetchone()
    daily = [dict(r) for r in conn.execute("SELECT * FROM daily ORDER BY day")]
    trades = [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 25")]
    return (dict(acct) if acct else None), daily, trades


def spy_history():
    hist = yf.Ticker(TREND_SYMBOL).history(period="2y", interval="1d", auto_adjust=False)
    closes = hist["Close"].dropna()
    ma = closes.rolling(MA_DAYS).mean()
    return closes, ma


def last_price(symbol: str) -> float | None:
    try:
        c = yf.Ticker(symbol).history(period="5d")["Close"].dropna()
        return float(c.iloc[-1]) if not c.empty else None
    except Exception:
        return None


def main():
    acct, daily, trades = load_db()
    closes, ma = spy_history()
    spy_now, ma_now = float(closes.iloc[-1]), float(ma.iloc[-1])
    gap = 100 * (spy_now / ma_now - 1)
    signal_in = spy_now > ma_now

    cash = acct["cash"] if acct else START_CAPITAL_USD
    held = acct["symbol"] if acct else None
    shares = acct["shares"] if acct else 0
    held_px = last_price(held) if held and shares else None
    equity = cash + (shares * held_px if held_px else 0.0)
    ret = 100 * (equity / START_CAPITAL_USD - 1)

    # Buy-and-hold SPY from the agent's first day, same starting money
    if daily:
        first_spy = daily[0]["spy_price"]
        bh_now = START_CAPITAL_USD * spy_now / first_spy
        since = daily[0]["day"]
    else:
        bh_now, since = START_CAPITAL_USD, None
    bh_ret = 100 * (bh_now / START_CAPITAL_USD - 1)

    holding_label = held if held and shares else "Cash"
    holding_color = GREEN if held == TREND_SYMBOL else BLUE if held == CASH_SYMBOL else MUTED
    signal_label = f"IN — hold {TREND_SYMBOL}" if signal_in else f"OUT — hold {CASH_SYMBOL}"
    signal_color = GREEN if signal_in else RED
    flip_word = "falls" if signal_in else "rises"
    flip_sub = f"switches if {TREND_SYMBOL} {flip_word} {abs(gap):.2f}% to ${ma_now:,.2f}"
    pending = ""
    want = TREND_SYMBOL if signal_in else CASH_SYMBOL
    if held and shares and held != want:
        pending = f"Next 3:50 PM check would switch {held} → {want}"
    elif not (held and shares):
        pending = f"Next 3:50 PM check will buy {want}"

    # Chart 1: SPY vs MA, last ~1 year
    tail = closes.tail(260)
    c_labels = [d.strftime("%Y-%m-%d") for d in tail.index]
    c_spy = [round(float(v), 2) for v in tail]
    c_ma = [round(float(v), 2) for v in ma.reindex(tail.index)]
    switch_pts = [None] * len(c_labels)
    idx = {d: i for i, d in enumerate(c_labels)}
    for t in trades:
        if t["action"] == "BUY":
            d = t["ts"][:10]
            if d in idx:
                switch_pts[idx[d]] = c_spy[idx[d]]

    # Chart 2: account vs buy-and-hold
    e_labels = [r["day"] for r in daily]
    e_agent = [r["equity"] for r in daily]
    e_bh = [round(START_CAPITAL_USD * r["spy_price"] / daily[0]["spy_price"], 2) for r in daily] if daily else []
    if daily and e_labels[-1] != datetime.now().strftime("%Y-%m-%d"):
        e_labels.append(datetime.now().strftime("%Y-%m-%d"))
        e_agent.append(round(equity, 2))
        e_bh.append(round(bh_now, 2))

    trade_rows = "".join(
        f'<tr><td>{t["ts"][:16].replace("T", " ")}</td>'
        f'<td style="color:{GREEN if t["action"] == "BUY" else RED};font-weight:700">{t["action"]}</td>'
        f'<td><b>{t["symbol"]}</b></td><td>{t["shares"]}</td><td>{money(t["price"])}</td>'
        f'<td>{money(t["amount_usd"])}</td><td class="muted">{t["mode"]}</td></tr>'
        for t in trades
    ) or '<tr><td colspan="7" class="empty">No trades yet — first check runs at 3:50 PM ET</td></tr>'

    day_rows = "".join(
        f'<tr><td>{r["day"]}</td><td>{money(r["spy_price"])}</td><td>{money(r["ma"])}</td>'
        f'<td style="color:{GREEN if r["signal"] == "IN" else RED};font-weight:700">{r["signal"]}</td>'
        f'<td>{r["shares"]} {r["holding"] or "-"}</td><td>{money(r["equity"])}</td></tr>'
        for r in reversed(daily[-30:])
    ) or '<tr><td colspan="6" class="empty">No daily checks yet</td></tr>'

    mode = "PAPER MODE" if PAPER_TRADING else "LIVE"
    now = datetime.now().strftime("%H:%M")
    since_txt = f"since {since}" if since else "not started"

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>SPY Trend Agent</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0f1e;color:#c8d8f0;font-family:-apple-system,sans-serif}}
.header{{background:#0e1626;border-bottom:1px solid #1e2d4a;padding:18px 24px;
display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}}
.title{{font-size:20px;font-weight:800;color:#fff}}
.subtitle{{font-size:12px;color:{BLUE};margin-top:3px}}
.badge{{background:#5aa9ff1a;color:{BLUE};border:1px solid #5aa9ff44;padding:4px 10px;border-radius:4px;font-size:11px}}
.meta{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:11px;color:{MUTED}}}
.meta a{{color:{MUTED};text-decoration:none}}
.main{{padding:22px 24px;max-width:1300px;margin:0 auto}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:12px}}
.card{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:18px}}
.label{{font-size:10px;color:{MUTED};letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px}}
.val{{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums}}
.sub{{font-size:11px;color:{MUTED};margin-top:5px}}
.note{{background:#ffd60a14;border:1px solid #ffd60a44;color:#ffd60a;border-radius:8px;padding:10px 14px;font-size:12px;margin-bottom:20px}}
.sec{{font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:{MUTED};
margin:8px 0 12px;padding-bottom:8px;border-bottom:1px solid #1e2d4a}}
.charts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px;margin-bottom:22px}}
.chart-card{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:16px}}
.chart-box{{position:relative;height:260px}}
.tables{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}
.tw{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;overflow-x:auto;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse}}
th{{font-size:10px;color:{MUTED};letter-spacing:.1em;text-transform:uppercase;padding:10px 12px;text-align:left;background:#162038;font-weight:400}}
td{{font-size:12px;padding:10px 12px;border-bottom:1px solid #1e2d4a55;font-family:Menlo,Courier,monospace;white-space:nowrap}}
tr:last-child td{{border-bottom:none}}
.muted{{color:{MUTED}}} .empty{{text-align:center;color:#667;padding:22px;font-family:inherit}}
.rule{{font-size:12px;color:{MUTED};line-height:1.6;margin-top:6px}}
</style></head><body>
<div class="header">
  <div>
    <div class="title">SPY TREND AGENT</div>
    <div class="subtitle">Hold {TREND_SYMBOL} above its {MA_DAYS}-day average · {CASH_SYMBOL} (T-bills) below</div>
  </div>
  <div class="meta">
    <span class="badge">● {mode}</span>
    <span class="badge">{since_txt}</span>
    <a href="/dashboard.html">← Equity Dashboard</a>
    <span>Updated {now} · auto-refresh 5m</span>
  </div>
</div>
<div class="main">
  <div class="stats">
    <div class="card"><div class="label">Holding</div>
      <div class="val" style="color:{holding_color}">{holding_label}</div>
      <div class="sub">{shares} shares · cash {money(cash)}</div></div>
    <div class="card"><div class="label">Signal now</div>
      <div class="val" style="color:{signal_color}">{"IN" if signal_in else "OUT"}</div>
      <div class="sub">{signal_label}</div></div>
    <div class="card"><div class="label">{TREND_SYMBOL} vs {MA_DAYS}-day</div>
      <div class="val" style="color:{signal_color}">{pct(gap)}</div>
      <div class="sub">{money(spy_now)} vs {money(ma_now)}</div></div>
    <div class="card"><div class="label">Distance to switch</div>
      <div class="val" style="color:#fff">{abs(gap):.2f}%</div>
      <div class="sub">{flip_sub}</div></div>
    <div class="card"><div class="label">Account value</div>
      <div class="val" style="color:{GREEN if ret >= 0 else RED}">{money(equity)}</div>
      <div class="sub">{money(equity - START_CAPITAL_USD, True)} ({pct(ret)}) from {money(START_CAPITAL_USD)}</div></div>
    <div class="card"><div class="label">vs buy-and-hold {TREND_SYMBOL}</div>
      <div class="val" style="color:{GREEN if ret - bh_ret >= 0 else RED}">{pct(ret - bh_ret)}</div>
      <div class="sub">buy-and-hold {pct(bh_ret)} over the same days</div></div>
  </div>
  {f'<div class="note">{pending}</div>' if pending else '<div style="height:10px"></div>'}

  <div class="charts">
    <div class="chart-card"><div class="label">{TREND_SYMBOL} and its {MA_DAYS}-day average · last 12 months</div>
      <div class="chart-box"><canvas id="spyChart"></canvas></div></div>
    <div class="chart-card"><div class="label">Account vs buy-and-hold {TREND_SYMBOL} (same {money(START_CAPITAL_USD)} start)</div>
      <div class="chart-box"><canvas id="eqChart"></canvas></div></div>
  </div>

  <div class="tables">
    <div><div class="sec">Trades</div><div class="tw"><table>
      <thead><tr><th>Time</th><th>Action</th><th>Symbol</th><th>Shares</th><th>Price</th><th>Amount</th><th>Mode</th></tr></thead>
      <tbody>{trade_rows}</tbody></table></div></div>
    <div><div class="sec">Daily checks (3:50 PM ET)</div><div class="tw"><table>
      <thead><tr><th>Day</th><th>{TREND_SYMBOL}</th><th>{MA_DAYS}-day</th><th>Signal</th><th>Holding</th><th>Account</th></tr></thead>
      <tbody>{day_rows}</tbody></table></div></div>
  </div>
  <div class="rule">Rule: every weekday at 3:50 PM ET, if {TREND_SYMBOL} is above its {MA_DAYS}-day average the account holds {TREND_SYMBOL}; otherwise it holds {CASH_SYMBOL}.
  Backtest 2007–2026: 9.0% a year with a −20.5% worst drop, vs buy-and-hold 10.8% a year with a −55.2% worst drop.</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
(function() {{
  var grid = "#1e2d4a", tick = {{ color: "{MUTED}", font: {{ size: 10 }} }};
  var common = {{ responsive: true, maintainAspectRatio: false, interaction: {{ mode: "index", intersect: false }},
    plugins: {{ legend: {{ labels: {{ color: "#c8d8f0", font: {{ size: 11 }}, boxWidth: 12 }} }} }},
    scales: {{ x: {{ ticks: Object.assign({{ maxTicksLimit: 6 }}, tick), grid: {{ color: grid }} }},
              y: {{ ticks: tick, grid: {{ color: grid }} }} }} }};
  new Chart(document.getElementById("spyChart"), {{
    type: "line",
    data: {{ labels: {json.dumps(c_labels)}, datasets: [
      {{ label: "{TREND_SYMBOL}", data: {json.dumps(c_spy)}, borderColor: "{BLUE}", borderWidth: 1.8, pointRadius: 0, tension: 0.1 }},
      {{ label: "{MA_DAYS}-day average", data: {json.dumps(c_ma)}, borderColor: "#ffd60a", borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0 }},
      {{ label: "Agent buys", data: {json.dumps(switch_pts)}, borderColor: "{GREEN}", backgroundColor: "{GREEN}", showLine: false, pointRadius: 5 }}
    ] }},
    options: common
  }});
  new Chart(document.getElementById("eqChart"), {{
    type: "line",
    data: {{ labels: {json.dumps(e_labels)}, datasets: [
      {{ label: "Trend agent", data: {json.dumps(e_agent)}, borderColor: "{GREEN}", borderWidth: 2, pointRadius: 2, tension: 0.1 }},
      {{ label: "Buy-and-hold {TREND_SYMBOL}", data: {json.dumps(e_bh)}, borderColor: "{MUTED}", borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0 }}
    ] }},
    options: common
  }});
}})();
</script>
</body></html>"""

    for out in OUTPUTS:
        Path(out).write_text(html)
    print(f"Trend dashboard saved: {', '.join(OUTPUTS)}")


if __name__ == "__main__":
    main()
