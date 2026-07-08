#!/usr/bin/env python3
"""Generate options_dashboard.html from db/options_trades.db."""

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from config.options_settings import OPTIONS_DB_PATH, MAX_OPTIONS_POSITIONS
from data.options_fetcher import get_option_premium
from core.options.chain import OptionsContract

OUTPUT = "options_dashboard.html"


def get_data():
    if not Path(OPTIONS_DB_PATH).exists():
        return None

    conn = sqlite3.connect(OPTIONS_DB_PATH)
    conn.row_factory = sqlite3.Row

    def rows(sql):
        return [dict(r) for r in conn.execute(sql).fetchall()]

    positions = rows(
        "SELECT * FROM options_positions WHERE status='OPEN' ORDER BY entry_ts DESC"
    )
    trades = rows("SELECT * FROM options_trades ORDER BY ts DESC LIMIT 20")
    pnl = rows("SELECT * FROM options_pnl ORDER BY exit_ts DESC LIMIT 20")
    signals = rows(
        "SELECT * FROM options_signals WHERE direction != 'NONE' ORDER BY ts DESC LIMIT 30"
    )
    total_pnl = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd),0) FROM options_pnl"
    ).fetchone()[0]
    wins = conn.execute(
        "SELECT COUNT(*) FROM options_pnl WHERE pnl_usd > 0"
    ).fetchone()[0]
    losses = conn.execute(
        "SELECT COUNT(*) FROM options_pnl WHERE pnl_usd <= 0"
    ).fetchone()[0]
    closed = wins + losses
    win_rate = (wins / closed * 100) if closed > 0 else 0
    tot_sigs = conn.execute(
        "SELECT COUNT(*) FROM options_signals WHERE direction != 'NONE'"
    ).fetchone()[0]
    tot_trades = conn.execute("SELECT COUNT(*) FROM options_trades").fetchone()[0]
    try:
        sv_row = conn.execute(
            "SELECT version, ts FROM options_strategy_log ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        strategy_version = sv_row["version"] if sv_row else ""
        strategy_since = str(sv_row["ts"])[:10] if sv_row else ""
    except Exception:
        strategy_version = ""
        strategy_since = ""
    conn.close()

    try:
        from core.market_trend import get_market_trend
        trend_data = get_market_trend()
        market_trend = trend_data["trend"]
        trend_spy = trend_data.get("spy_price")
        trend_ma50 = trend_data.get("ma50")
    except Exception:
        market_trend = "UNKNOWN"
        trend_spy = trend_ma50 = None

    print("Fetching option premiums for open positions...")
    total_unrealized = 0
    today = date.today()
    for pos in positions:
        exp = date.fromisoformat(pos["expiration"])
        pos["dte"] = (exp - today).days
        contract = OptionsContract(
            underlying=pos["underlying"],
            option_type=pos["option_type"],
            strike=float(pos["strike"]),
            expiration=exp,
            bid=0, ask=0, last=0, volume=0, open_interest=0,
            implied_volatility=0, in_the_money=False,
            contract_symbol=pos["contract_symbol"],
        )
        premium = get_option_premium(contract)
        pos["current_premium"] = premium
        entry = float(pos["entry_premium"])
        contracts = int(pos["contracts"])
        if premium and entry > 0:
            unreal = (premium - entry) * contracts * 100
            pct = (premium - entry) / entry * 100
            pos["unrealized_pnl"] = round(unreal, 2)
            pos["unrealized_pct"] = round(pct, 2)
            total_unrealized += round(unreal, 2)
        else:
            pos["unrealized_pnl"] = None
            pos["unrealized_pct"] = None

    return {
        "summary": {
            "total_pnl": round(total_pnl, 2),
            "total_unrealized": round(total_unrealized, 2),
            "win_rate": round(win_rate, 1),
            "wins": wins,
            "losses": losses,
            "closed_trades": closed,
            "open_positions": len(positions),
            "total_signals": tot_sigs,
            "total_trades": tot_trades,
            "total_combined": round(total_pnl + total_unrealized, 2),
            "market_trend": market_trend,
            "trend_color": (
                "#00c896" if market_trend == "BULL"
                else "#ff4d6d" if market_trend == "BEAR"
                else "#ffd60a"
            ),
            "trend_sub": (
                f"SPY ${trend_spy:.0f} MA50 ${trend_ma50:.0f}"
                if trend_spy else "fetching..."
            ),
            "strategy_version": strategy_version,
            "strategy_since": strategy_since,
        },
        "positions": positions,
        "trades": trades,
        "pnl": pnl,
        "signals": signals,
    }


def badge_option(option_type: str) -> str:
    c = "#00c896" if option_type == "CALL" else "#ff4d6d"
    return (
        f'<span style="background:{c}22;color:{c};padding:2px 8px;'
        f'border-radius:3px;font-size:11px;font-weight:700">{option_type}</span>'
    )


def badge_dir(direction: str) -> str:
    label = "CALL" if direction == "BUY" else "PUT"
    return badge_option(label)


def pspan(val, suffix=""):
    if val is None:
        return '<span style="color:#4a6080">—</span>'
    c = "#00c896" if float(val) >= 0 else "#ff4d6d"
    sign = "+" if float(val) >= 0 else ""
    return f'<span style="color:{c}">{sign}{float(val):.2f}{suffix}</span>'


def main():
    print("Reading options database...")
    data = get_data()
    if not data:
        print(f"ERROR: {OPTIONS_DB_PATH} not found.")
        return

    s = data["summary"]
    pnl_color = "#00c896" if s["total_pnl"] >= 0 else "#ff4d6d"
    pnl_str = ("+$" if s["total_pnl"] >= 0 else "-$") + str(abs(s["total_pnl"]))
    unreal_color = "#00c896" if s["total_unrealized"] >= 0 else "#ff4d6d"
    unreal_str = (
        ("+$" if s["total_unrealized"] >= 0 else "-$")
        + str(abs(s["total_unrealized"]))
    )
    combined = s["total_combined"]
    combined_color = "#00c896" if combined >= 0 else "#ff4d6d"
    combined_str = ("+$" if combined >= 0 else "-$") + str(abs(combined))
    now_hhmm = datetime.now().strftime("%H:%M")
    strat_ver = s.get("strategy_version", "")
    strat_since = s.get("strategy_since", "")
    strat_badge = (
        f'<span style="background:#7b61ff22;color:#b794f6;border:1px solid #7b61ff44;'
        f'padding:4px 12px;border-radius:4px;font-size:11px">'
        f'{strat_ver} · since {strat_since}</span>'
        if strat_ver else ""
    )

    pos_rows = ""
    for r in data["positions"]:
        cur = (
            f'${float(r["current_premium"]):.2f}'
            if r.get("current_premium") else "—"
        )
        if r.get("current_premium"):
            cur_color = (
                "#00c896" if r["current_premium"] >= r["entry_premium"]
                else "#ff4d6d"
            )
            cur_html = f'<span style="color:{cur_color};font-weight:700">{cur}</span>'
        else:
            cur_html = "—"
        dte = r.get("dte", "—")
        dte_color = "#ff4d6d" if isinstance(dte, int) and dte <= 7 else "#c8d8f0"
        ts = str(r.get("entry_ts", ""))[:16].replace("T", " ")
        pos_rows += (
            f'<tr><td><b>{r["underlying"]}</b></td>'
            f'<td>{badge_option(r["option_type"])}</td>'
            f'<td>${float(r["strike"]):.0f}</td>'
            f'<td style="color:#888">{r["expiration"]}</td>'
            f'<td style="color:{dte_color};text-align:center">{dte}</td>'
            f'<td>{r["contracts"]}</td>'
            f'<td>${float(r["entry_premium"]):.2f}</td>'
            f'<td>{cur_html}</td>'
            f'<td>{pspan(r.get("unrealized_pnl"))}</td>'
            f'<td>{pspan(r.get("unrealized_pct"), "%")}</td>'
            f'<td style="color:#ff4d6d">${float(r["stop_loss"]):.2f}</td>'
            f'<td style="color:#00c896">${float(r["take_profit"]):.2f}</td>'
            f'<td style="color:#888;font-size:10px">{r["contract_symbol"][-15:]}</td>'
            f'<td style="color:#888">{ts}</td></tr>'
        )
    if not pos_rows:
        pos_rows = (
            '<tr><td colspan="14" style="text-align:center;color:#666;'
            'padding:24px">No open option positions</td></tr>'
        )

    trade_rows = "".join([
        f'<tr><td><b>{r["underlying"]}</b></td>'
        f'<td>{badge_option(r["option_type"])}</td>'
        f'<td>{r["contracts"]}</td>'
        f'<td>${float(r["premium"]):.2f}</td>'
        f'<td style="color:#ffd60a;font-size:11px">{r["mode"]}</td>'
        f'<td style="color:#888">{str(r.get("ts",""))[:16]}</td></tr>'
        for r in data["trades"]
    ]) or (
        '<tr><td colspan="6" style="text-align:center;color:#666;'
        'padding:24px">No trades yet</td></tr>'
    )

    pnl_rows = "".join([
        f'<tr><td><b>{r["underlying"]}</b></td>'
        f'<td>{badge_option(r["option_type"])}</td>'
        f'<td>{pspan(r["pnl_usd"])}</td>'
        f'<td>{pspan(r["pnl_pct"], "%")}</td>'
        f'<td style="color:#888">{str(r.get("exit_ts",""))[:16]}</td></tr>'
        for r in data["pnl"]
    ]) or (
        '<tr><td colspan="5" style="text-align:center;color:#666;'
        'padding:24px">No closed trades yet</td></tr>'
    )

    sig_rows = "".join([
        f'<tr><td style="color:#888">{str(r.get("ts",""))[:16]}</td>'
        f'<td><b>{r["underlying"]}</b></td>'
        f'<td>{badge_dir(r["direction"])}</td>'
        f'<td style="color:#ffd60a">{"★"*min(r.get("confirmations",0),3)}</td>'
        f'<td>{r.get("rsi","—")}</td>'
        f'<td>${float(r["close_price"]):.2f}</td>'
        f'<td style="color:#888;font-size:11px">{r.get("reason","")[:60]}</td></tr>'
        for r in data["signals"]
    ]) or (
        '<tr><td colspan="7" style="text-align:center;color:#666;'
        'padding:24px">No signals yet</td></tr>'
    )

    cum_labels, cum_values = [], []
    running = 0
    for r in sorted(data["pnl"], key=lambda x: x.get("exit_ts", "")):
        running += float(r["pnl_usd"])
        cum_labels.append(str(r.get("exit_ts", ""))[:10])
        cum_values.append(round(running, 2))
    if cum_labels:
        cum_labels.append(datetime.now().strftime("%Y-%m-%d"))
        cum_values.append(round(running + s["total_unrealized"], 2))

    bar_labels = [p["underlying"] for p in data["positions"]]
    bar_values = [
        p["unrealized_pnl"] if p.get("unrealized_pnl") is not None else 0
        for p in data["positions"]
    ]
    bar_colors = ["#00c896" if v >= 0 else "#ff4d6d" for v in bar_values]
    line_color = (
        "#00c896" if not cum_values or cum_values[-1] >= 0 else "#ff4d6d"
    )

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta http-equiv="refresh" content="300">
<title>Options Trading Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0f1e;color:#c8d8f0;font-family:-apple-system,sans-serif}}
.header{{background:#120f1e;border-bottom:1px solid #2d1e4a;padding:20px 32px;
display:flex;justify-content:space-between;align-items:center}}
.title{{font-size:20px;font-weight:800;color:#fff}}
.subtitle{{font-size:12px;color:#b794f6;margin-top:3px}}
.main{{padding:28px 32px}}
.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin-bottom:28px}}
.card{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:20px}}
.label{{font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px}}
.val{{font-size:24px;font-weight:800}}
.sub{{font-size:11px;color:#4a6080;margin-top:5px}}
.sec{{font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;
color:#4a6080;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e2d4a}}
.tw{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;overflow:hidden;margin-bottom:24px}}
table{{width:100%;border-collapse:collapse}}
th{{font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;
padding:10px 14px;text-align:left;background:#162038;font-weight:400}}
td{{font-size:12px;padding:11px 14px;border-bottom:1px solid #1e2d4a33;font-family:Courier,monospace}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#7b61ff06}}
.charts{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:24px}}
.chart-card{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:16px}}
</style></head><body>
<div class="header">
  <div>
    <div class="title">📈 OPTIONS AGENT</div>
    <div class="subtitle">PAPER PORTFOLIO · LONG CALLS &amp; PUTS</div>
  </div>
  <div style="display:flex;align-items:center;gap:16px">
    <span style="background:#7b61ff22;color:#b794f6;border:1px solid #7b61ff44;
padding:4px 12px;border-radius:4px;font-size:11px">● PAPER MODE</span>
    {strat_badge}
    <a href="http://localhost:8080/dashboard.html" style="color:#4a6080;font-size:11px;
text-decoration:none">← Equity Dashboard</a>
    <span style="font-size:11px;color:#4a6080">Updated: {now_hhmm} · auto-refresh 5m</span>
  </div>
</div>
<div class="main">
  <div class="stats">
    <div class="card" style="border-color:#7b61ff44">
      <div class="label" style="color:#b794f6">Total Portfolio</div>
      <div class="val" style="color:{combined_color}">{combined_str}</div>
      <div class="sub">realized + unrealized</div></div>
    <div class="card"><div class="label">Realized P&amp;L</div>
      <div class="val" style="color:{pnl_color}">{pnl_str}</div>
      <div class="sub">{s["closed_trades"]} closed trades</div></div>
    <div class="card"><div class="label">Unrealized P&amp;L</div>
      <div class="val" style="color:{unreal_color}">{unreal_str}</div>
      <div class="sub">open contracts</div></div>
    <div class="card"><div class="label">Win Rate</div>
      <div class="val" style="color:#00c896">{s["win_rate"]}%</div>
      <div class="sub">{s["wins"]}W / {s["losses"]}L</div></div>
    <div class="card"><div class="label">Open Positions</div>
      <div class="val" style="color:#fff">{s["open_positions"]}</div>
      <div class="sub">of {MAX_OPTIONS_POSITIONS} max</div></div>
    <div class="card"><div class="label">Market Trend</div>
      <div class="val" style="color:{s["trend_color"]}">{s["market_trend"]}</div>
      <div class="sub">{s["trend_sub"]}</div></div>
    <div class="card"><div class="label">Signals / Trades</div>
      <div class="val" style="color:#b794f6">{s["total_signals"]}</div>
      <div class="sub">{s["total_trades"]} executed</div></div>
  </div>

  <div class="sec">Open Option Positions — Live Premiums</div>
  <div class="tw"><table>
    <thead><tr>
      <th>Underlying</th><th>Type</th><th>Strike</th><th>Expiry</th><th>DTE</th>
      <th>Contracts</th><th>Entry Prem</th><th>Current Prem</th>
      <th>Unreal $</th><th>Unreal %</th><th>Stop</th><th>Take Profit</th>
      <th>Contract</th><th>Opened</th>
    </tr></thead>
    <tbody>{pos_rows}</tbody>
  </table></div>

  <div class="sec">Performance Charts</div>
  <div class="charts">
    <div class="chart-card">
      <div class="label">Win / Loss</div>
      <canvas id="donutChart" height="160"></canvas></div>
    <div class="chart-card">
      <div class="label">Open P&amp;L by Position</div>
      <canvas id="barChart" height="160"></canvas></div>
    <div class="chart-card">
      <div class="label">Cumulative P&amp;L</div>
      <canvas id="lineChart" height="160"></canvas></div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px">
    <div><div class="sec">Recent Trades</div><div class="tw"><table>
      <thead><tr><th>Underlying</th><th>Type</th><th>Qty</th><th>Premium</th>
      <th>Mode</th><th>Time</th></tr></thead>
      <tbody>{trade_rows}</tbody></table></div></div>
    <div><div class="sec">Closed P&amp;L</div><div class="tw"><table>
      <thead><tr><th>Underlying</th><th>Type</th><th>P&amp;L $</th><th>P&amp;L %</th>
      <th>Closed</th></tr></thead>
      <tbody>{pnl_rows}</tbody></table></div></div>
    <div><div class="sec">Recent Signals</div><div class="tw"><table>
      <thead><tr><th>Time</th><th>Symbol</th><th>Dir</th><th>Conf</th><th>RSI</th>
      <th>Price</th><th>Reason</th></tr></thead>
      <tbody>{sig_rows}</tbody></table></div></div>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
(function() {{
  var wins = {s["wins"]};
  var losses = {s["losses"]};
  new Chart(document.getElementById("donutChart"), {{
    type: "doughnut",
    data: {{ labels: ["Wins","Losses"],
      datasets: [{{ data: [wins, losses], backgroundColor: ["#00c896","#ff4d6d"],
        borderWidth: 0 }}] }},
    options: {{ plugins: {{ legend: {{ labels: {{ color: "#4a6080", font: {{ size: 10 }} }} }} }},
      cutout: "65%" }}
  }});
  new Chart(document.getElementById("barChart"), {{
    type: "bar",
    data: {{ labels: {json.dumps(bar_labels)},
      datasets: [{{ data: {json.dumps(bar_values)},
        backgroundColor: {json.dumps(bar_colors)}, borderRadius: 4 }}] }},
    options: {{ plugins: {{ legend: {{ display: false }} }},
      scales: {{ x: {{ ticks: {{ color:"#4a6080",font:{{size:9}} }}, grid:{{color:"#1e2d4a"}} }},
        y: {{ ticks: {{ color:"#4a6080",font:{{size:9}} }}, grid:{{color:"#1e2d4a"}} }} }}
  }});
  new Chart(document.getElementById("lineChart"), {{
    type: "line",
    data: {{ labels: {json.dumps(cum_labels)},
      datasets: [{{ data: {json.dumps(cum_values)}, borderColor: "{line_color}",
        backgroundColor: "{line_color}18", fill: true, tension: 0.3,
        pointRadius: 4, borderWidth: 2 }}] }},
    options: {{ plugins: {{ legend: {{ display: false }} }},
      scales: {{ x: {{ ticks: {{ color:"#4a6080",font:{{size:9}},maxTicksLimit:6 }},
        grid:{{color:"#1e2d4a"}} }},
        y: {{ ticks: {{ color:"#4a6080",font:{{size:9}} }}, grid:{{color:"#1e2d4a"}} }} }}
  }});
}})();
</script>
</body></html>"""

    Path(OUTPUT).write_text(html)
    print(f"Options dashboard saved: {OUTPUT}")


if __name__ == "__main__":
    main()
