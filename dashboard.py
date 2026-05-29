#!/usr/bin/env python3
import sqlite3, webbrowser, os, json
import yfinance as yf
from pathlib import Path
from datetime import datetime

DB_PATH = "db/trades.db"
OUTPUT = "dashboard.html"

def get_current_price(symbol):
    try:
        import requests_cache
        requests_cache.disabled()
    except Exception:
        pass
    try:
        # Force fresh data by creating new ticker instance with no_cache
        ticker = yf.Ticker(symbol)
        # Use history with 1d period to get most recent price — more reliable than fast_info
        hist = ticker.history(period="1d", interval="1m", auto_adjust=True)
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            return round(price, 4)
        # Fallback to fast_info
        price = ticker.fast_info.last_price
        return round(float(price), 4) if price else None
    except Exception:
        return None

def get_data():
    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    def rows(sql):
        return [dict(r) for r in conn.execute(sql).fetchall()]
    positions = rows("SELECT * FROM positions WHERE status='OPEN' ORDER BY entry_ts DESC")
    trades = rows("SELECT * FROM trades ORDER BY ts DESC LIMIT 20")
    pnl = rows("SELECT * FROM pnl ORDER BY exit_ts DESC LIMIT 20")
    signals = rows("SELECT * FROM signals WHERE direction != 'NONE' ORDER BY ts DESC LIMIT 30")
    total_pnl = conn.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM pnl").fetchone()[0]
    wins = conn.execute("SELECT COUNT(*) FROM pnl WHERE pnl_usd > 0").fetchone()[0]
    losses = conn.execute("SELECT COUNT(*) FROM pnl WHERE pnl_usd <= 0").fetchone()[0]
    closed = wins + losses
    win_rate = (wins / closed * 100) if closed > 0 else 0
    tot_sigs = conn.execute("SELECT COUNT(*) FROM signals WHERE direction != 'NONE'").fetchone()[0]
    tot_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    try:
        sv_row = conn.execute(
            "SELECT version, ts FROM strategy_log ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        strategy_version = sv_row["version"] if sv_row else ""
        strategy_since = str(sv_row["ts"])[:10] if sv_row else ""
    except Exception:
        strategy_version = ""
        strategy_since = ""
    conn.close()

    # Get market trend
    try:
        from core.market_trend import get_market_trend
        trend_data = get_market_trend()
        market_trend     = trend_data["trend"]
        trend_spy        = trend_data.get("spy_price")
        trend_ma50       = trend_data.get("ma50")
        trend_allow_buy  = trend_data.get("allow_buy", True)
        trend_allow_sell = trend_data.get("allow_sell", True)
    except Exception as e:
        market_trend = "UNKNOWN"
        trend_spy = trend_ma50 = None
        trend_allow_buy = trend_allow_sell = True

    # Fetch current prices and unrealized P&L
    print("Fetching current prices for open positions...")
    total_unrealized = 0
    for pos in positions:
        sym = pos["symbol"]
        current = get_current_price(sym)
        print(f"  {sym}: ${current}")
        pos["current_price"] = current
        if current:
            if pos["action"] == "BUY":
                unreal = (current - pos["entry_price"]) * pos["quantity"]
                pct = (current - pos["entry_price"]) / pos["entry_price"] * 100
            else:
                unreal = (pos["entry_price"] - current) * pos["quantity"]
                pct = (pos["entry_price"] - current) / pos["entry_price"] * 100
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
            "wins": wins, "losses": losses,
            "closed_trades": closed,
            "open_positions": len(positions),
            "total_signals": tot_sigs,
            "total_trades": tot_trades,
            "total_combined": round(total_pnl + total_unrealized, 2),
            "market_trend":  market_trend,
            "trend_color":   "#00c896" if market_trend=="BULL" else "#ff4d6d" if market_trend=="BEAR" else "#ffd60a",
            "trend_sub":     f"SPY ${trend_spy:.0f} MA50 ${trend_ma50:.0f}" if trend_spy else "fetching...",
            "allow_buy":        trend_allow_buy,
            "allow_sell":       trend_allow_sell,
            "strategy_version": strategy_version,
            "strategy_since":   strategy_since,
        },
        "positions": positions, "trades": trades, "pnl": pnl, "signals": signals,
    }

def badge(action):
    c = "#00c896" if action == "BUY" else "#ff4d6d"
    return f'<span style="background:{c}22;color:{c};padding:2px 8px;border-radius:3px;font-size:11px;font-weight:700">{action}</span>'

def pspan(val, suffix=""):
    if val is None: return '<span style="color:#4a6080">—</span>'
    c = "#00c896" if float(val) >= 0 else "#ff4d6d"
    return f'<span style="color:{c}">{("+" if float(val)>=0 else "")}{float(val):.2f}{suffix}</span>'

def main():
    print("Reading database...")
    data = get_data()
    if not data:
        print("ERROR: db/trades.db not found.")
        return
    s = data["summary"]
    pnl_color = "#00c896" if s["total_pnl"] >= 0 else "#ff4d6d"
    pnl_str = ("+$" if s["total_pnl"] >= 0 else "-$") + str(abs(s["total_pnl"]))
    unreal_color = "#00c896" if s["total_unrealized"] >= 0 else "#ff4d6d"
    unreal_str = ("+$" if s["total_unrealized"] >= 0 else "-$") + str(abs(s["total_unrealized"]))
    combined = s["total_combined"]
    combined_color = "#00c896" if combined >= 0 else "#ff4d6d"
    combined_str = ("+$" if combined >= 0 else "-$") + str(abs(combined))
    now = datetime.now().strftime("%b %d %Y %I:%M %p")
    now_hhmm = datetime.now().strftime("%H:%M")
    strat_ver = s.get("strategy_version", "")
    strat_since = s.get("strategy_since", "")
    strat_badge = (
        f'<span style="background:#ffd60a22;color:#ffd60a;border:1px solid #ffd60a44;'
        f'padding:4px 12px;border-radius:4px;font-size:11px">{strat_ver} · since {strat_since}</span>'
        if strat_ver else ""
    )

    # Market status
    from datetime import time as dtime
    import pytz
    et = pytz.timezone("US/Eastern")
    et_now = datetime.now(et)
    market_open_time  = dtime(9, 30)
    market_close_time = dtime(16, 0)
    is_weekday = et_now.weekday() < 5
    is_market_hours = market_open_time <= et_now.time() <= market_close_time
    market_open = is_weekday and is_market_hours
    market_status = "MARKET OPEN" if market_open else "MARKET CLOSED"
    market_color = "#00c896" if market_open else "#ff4d6d"
    et_time_str = et_now.strftime("%I:%M %p ET")

    # Chart data
    from datetime import date as date_type
    cum_labels = []
    cum_values = []
    running = 0
    for r in sorted(data["pnl"], key=lambda x: x.get("exit_ts","")):
        running += float(r["pnl_usd"])
        cum_labels.append(str(r.get("exit_ts",""))[:10])
        cum_values.append(round(running, 2))
    if cum_labels:
        cum_labels.append(now[:10])
        cum_values.append(round(running + s["total_unrealized"], 2))
    donut_wins = s["wins"]
    donut_losses = s["losses"]
    bar_labels = [p["symbol"] for p in data["positions"]]
    bar_values = [p["unrealized_pnl"] if p["unrealized_pnl"] is not None else 0 for p in data["positions"]]
    bar_colors = ["#00c896" if v >= 0 else "#ff4d6d" for v in bar_values]
    
    # Full position data for popup
    pos_js_data = []
    for p in data["positions"]:
        pos_js_data.append({
            "symbol": p["symbol"],
            "action": p["action"],
            "quantity": p["quantity"],
            "entry_price": p["entry_price"],
            "current_price": p.get("current_price"),
            "unrealized_pnl": p.get("unrealized_pnl"),
            "unrealized_pct": p.get("unrealized_pct"),
            "stop_loss": p["stop_loss"],
            "take_profit": p["take_profit"],
            "entry_ts": str(p.get("entry_ts",""))[:16],
        })
    pos_js_str = json.dumps(pos_js_data)

    # Full pnl data for line click
    pnl_js_data = []
    running2 = 0
    for r in sorted(data["pnl"], key=lambda x: x.get("exit_ts","")):
        running2 += float(r["pnl_usd"])
        pnl_js_data.append({
            "symbol": r["symbol"],
            "pnl_usd": r["pnl_usd"],
            "pnl_pct": r["pnl_pct"],
            "exit_date": str(r.get("exit_ts",""))[:10],
            "cumulative": round(running2, 2),
        })
    pnl_js_str = json.dumps(pnl_js_data)
    
    # Full trade data for donut filter
    all_pnl_js = json.dumps([{
        "symbol": r["symbol"],
        "pnl_usd": r["pnl_usd"],
        "pnl_pct": r["pnl_pct"],
        "exit_ts": str(r.get("exit_ts",""))[:16],
    } for r in data["pnl"]])

    # Positions rows with current price + unrealized P&L
    pos_rows = ""
    for r in data["positions"]:
        try:
            entry_dt = datetime.fromisoformat(str(r["entry_ts"]))
            days_held = (datetime.now() - entry_dt).days
            hours_held = (datetime.now() - entry_dt).seconds // 3600
            held_str = f"{hours_held}h" if days_held == 0 else f"{days_held}d"
            is_overnight = entry_dt.date() < date_type.today()
            pdt_html = '<span style="background:#00c89622;color:#00c896;padding:2px 6px;border-radius:3px;font-size:10px">OVERNIGHT</span>' if is_overnight else '<span style="background:#ffd60a22;color:#ffd60a;padding:2px 6px;border-radius:3px;font-size:10px">SAME DAY</span>'
        except:
            held_str = "-"
            pdt_html = "-"
        dummy = None  # continue below
        cur = f'${float(r["current_price"]):.3f}' if r["current_price"] else '—'
        # Color current price vs entry
        if r["current_price"]:
            if r["action"] == "BUY":
                cur_color = "#00c896" if r["current_price"] >= r["entry_price"] else "#ff4d6d"
            else:
                cur_color = "#00c896" if r["current_price"] <= r["entry_price"] else "#ff4d6d"
            cur_html = f'<span style="color:{cur_color};font-weight:700">{cur}</span>'
        else:
            cur_html = '—'
        ts = str(r.get("entry_ts",""))[:16].replace("T"," ")
        pos_rows += f'<tr><td><b>{r["symbol"]}</b></td><td>{badge(r["action"])}</td><td>{r["quantity"]}</td><td>${float(r["entry_price"]):.3f}</td><td>{cur_html}</td><td>{pspan(r["unrealized_pnl"])}</td><td>{pspan(r["unrealized_pct"],"%")}</td><td style="color:#ff4d6d">${float(r["stop_loss"]):.3f}</td><td style="color:#00c896">${float(r["take_profit"]):.3f}</td><td style="color:#c8d8f0;text-align:center">{held_str}</td><td>{pdt_html}</td><td style="color:#888">{ts}</td></tr>'
    if not pos_rows:
        pos_rows = '<tr><td colspan="12" style="text-align:center;color:#666;padding:24px">No open positions</td></tr>'

    trade_rows = "".join([f'<tr><td><b>{r["symbol"]}</b></td><td>{badge(r["action"])}</td><td>{r["quantity"]}</td><td>${float(r["price"]):.3f}</td><td style="color:#ffd60a;font-size:11px">{r["mode"]}</td><td style="color:#888">{str(r.get("ts",""))[:16]}</td></tr>' for r in data["trades"]]) or '<tr><td colspan="6" style="text-align:center;color:#666;padding:24px">No trades yet</td></tr>'
    pnl_rows = "".join([f'<tr><td><b>{r["symbol"]}</b></td><td>{pspan(r["pnl_usd"])}</td><td>{pspan(r["pnl_pct"],"%")}</td><td style="color:#888">{str(r.get("exit_ts",""))[:16]}</td></tr>' for r in data["pnl"]]) or '<tr><td colspan="4" style="text-align:center;color:#666;padding:24px">No closed trades yet</td></tr>'
    sig_rows = "".join([f'<tr><td style="color:#888">{str(r.get("ts",""))[:16]}</td><td><b>{r["symbol"]}</b></td><td>{badge(r["direction"])}</td><td style="color:#ffd60a">{"★"*r["confirmations"]}{"☆"*(3-r["confirmations"])}</td><td>{r.get("rsi_signal","—")}</td><td>{r.get("bband_signal","—")}</td><td>${float(r["close_price"]):.3f}</td><td style="color:#888;font-size:11px">{r.get("reason","")}</td></tr>' for r in data["signals"]]) or '<tr><td colspan="8" style="text-align:center;color:#666;padding:24px">No signals yet</td></tr>'

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Trading Dashboard</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0f1e;color:#c8d8f0;font-family:-apple-system,sans-serif}}.header{{background:#0f1729;border-bottom:1px solid #1e2d4a;padding:20px 32px;display:flex;justify-content:space-between;align-items:center}}.title{{font-size:20px;font-weight:800;color:#fff}}.subtitle{{font-size:12px;color:#00c896;margin-top:3px}}.main{{padding:28px 32px}}.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin-bottom:28px}}.card{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:20px}}.label{{font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px}}.val{{font-size:24px;font-weight:800}}.sub{{font-size:11px;color:#4a6080;margin-top:5px}}.sec{{font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:#4a6080;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e2d4a}}.tw{{background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;overflow:hidden;margin-bottom:24px}}table{{width:100%;border-collapse:collapse}}th{{font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;padding:10px 14px;text-align:left;background:#162038;font-weight:400}}td{{font-size:12px;padding:11px 14px;border-bottom:1px solid #1e2d4a33;font-family:Courier,monospace}}tr:last-child td{{border-bottom:none}}tr:hover td{{background:#00c89606}}.two{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}</style>
</head><body>
<div class="header">
  <div><div class="title">⚡ TRADING AGENT</div><div class="subtitle">PAPER PORTFOLIO · MEAN REVERSION</div></div>
  <div style="display:flex;align-items:center;gap:16px">
    <span style="background:#00c89622;color:#00c896;border:1px solid #00c89644;padding:4px 12px;border-radius:4px;font-size:11px">● PAPER MODE</span>
    {strat_badge}
    <span style="font-size:11px;color:#4a6080">Last updated: {now_hhmm}</span>
  </div>
</div>
<div class="main">
  <div class="stats">
    <div class="card" style="border-color:#ffd60a44"><div class="label" style="color:#ffd60a">Total Portfolio</div><div class="val" style="color:{combined_color}">{combined_str}</div><div class="sub">realized + unrealized</div></div>
    <div class="card"><div class="label">Realized P&L</div><div class="val" style="color:{pnl_color}">{pnl_str}</div><div class="sub">{s["closed_trades"]} closed trades</div></div>
    <div class="card"><div class="label">Unrealized P&L</div><div class="val" style="color:{unreal_color}">{unreal_str}</div><div class="sub">open positions</div></div>
    <div class="card"><div class="label">Win Rate</div><div class="val" style="color:#00c896">{s["win_rate"]}%</div><div class="sub">{s["wins"]}W / {s["losses"]}L</div></div>
    <div class="card"><div class="label">Open Positions</div><div class="val" style="color:#fff">{s["open_positions"]}</div><div class="sub">of 5 max</div></div>
    <div class="card"><div class="label">Market Trend</div><div class="val" style="color:{s["trend_color"]}">{s["market_trend"]}</div><div class="sub">{s["trend_sub"]}</div></div>
    <div class="card"><div class="label">Total Signals</div><div class="val" style="color:#00c896">{s["total_signals"]}</div><div class="sub">{s["total_trades"]} trades executed</div></div>
  </div>

  <div class="sec">Open Positions — Live Prices</div>
  <div class="tw"><table>
    <thead><tr><th>Symbol</th><th>Action</th><th>Qty</th><th>Entry</th><th>Current Price</th><th>Unreal P&L $</th><th>Unreal P&L %</th><th>Ref Stop¹</th><th>Take Profit</th><th>Held</th><th>PDT Status</th><th>Opened</th></tr></thead>
    <tbody>{pos_rows}</tbody>
  </table></div>

  <div style="font-size:10px;color:#4a6080;margin-top:-16px;margin-bottom:24px">¹ Reference only — fixed stop-loss exits removed in v3.0. Emergency floor at 10%.</div>

  <div class="sec">Performance Charts</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:24px">
    <div style="background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:16px">
      <div style="font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px">Win / Loss</div>
      <canvas id="donutChart" height="160"></canvas>
    </div>
    <div style="background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:16px">
      <div style="font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px">Open P&amp;L by Position</div>
      <canvas id="barChart" height="160"></canvas>
    </div>
    <div style="background:#0f1729;border:1px solid #1e2d4a;border-radius:10px;padding:16px">
      <div style="font-size:10px;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px">Cumulative P&amp;L</div>
      <canvas id="lineChart" height="160"></canvas>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:24px">
    <div><div class="sec">Recent Trades</div><div class="tw"><table>
      <thead><tr><th>Symbol</th><th>Action</th><th>Qty</th><th>Price</th><th>Mode</th><th>Time</th></tr></thead>
      <tbody>{trade_rows}</tbody>
    </table></div></div>
    <div><div class="sec">Closed P&L</div><div class="tw"><table>
      <thead><tr><th>Symbol</th><th>P&L $</th><th>P&L %</th><th>Closed</th></tr></thead>
      <tbody>{pnl_rows}</tbody>
    </table></div></div>
    <div>
      <div class="sec">Recent Signals</div>
      <div class="tw"><table>
        <thead><tr><th>Time</th><th>Symbol</th><th>Dir</th><th>Conf</th><th>RSI</th><th>BB</th><th>Price</th></tr></thead>
        <tbody>{sig_rows}</tbody>
      </table></div>
    </div>
  </div>

  <div style="display:none">CHARTS_PLACEHOLDER
  </div>
</div>
<!-- Modal popup -->
<div id="modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:1000;align-items:center;justify-content:center">
  <div style="background:#0f1729;border:1px solid #1e2d4a;border-radius:14px;padding:32px;min-width:340px;max-width:480px;position:relative">
    <button onclick="document.getElementById('modal').style.display='none'" style="position:absolute;top:14px;right:16px;background:none;border:none;color:#4a6080;font-size:20px;cursor:pointer">x</button>
    <div id="modal-content"></div>
  </div>
</div>

<!-- Trade filter panel -->
<div id="trade-filter-bar" style="display:none;background:#162038;border:1px solid #1e2d4a;border-radius:8px;padding:10px 16px;margin:-16px 32px 16px;font-size:11px;color:#c8d8f0;display:flex;align-items:center;gap:12px">
  <span id="filter-label" style="color:#ffd60a">Showing: All trades</span>
  <button onclick="clearFilter()" style="background:#ff4d6d22;color:#ff4d6d;border:1px solid #ff4d6d44;border-radius:4px;padding:3px 10px;cursor:pointer;font-size:10px">Clear Filter</button>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
(function() {{
  var wins = {donut_wins};
  var losses = {donut_losses};
  var barLabels = {bar_labels};
  var barValues = {bar_values};
  var barColors = {bar_colors};
  var lineLabels = {cum_labels};
  var lineValues = {cum_values};
  var lineColor = lineValues.length > 0 && lineValues[lineValues.length-1] >= 0 ? "#00c896" : "#ff4d6d";
  var posData = {pos_js_str};
  var pnlData = {pnl_js_str};
  var allPnl = {all_pnl_js};

  // ── Popup helper ──
  function showModal(html) {{
    document.getElementById("modal-content").innerHTML = html;
    document.getElementById("modal").style.display = "flex";
  }}

  // ── Donut — Win/Loss filter ──
  var donutChart = new Chart(document.getElementById("donutChart"), {{
    type: "doughnut",
    data: {{ labels: ["Wins","Losses"], datasets: [{{ data: [wins, losses], backgroundColor: ["#00c896","#ff4d6d"], borderWidth: 0, hoverOffset: 8 }}] }},
    options: {{
      plugins: {{
        legend: {{ display: true, position: "bottom", labels: {{ color: "#4a6080", font: {{ size: 10 }}, padding: 8 }} }},
        tooltip: {{ callbacks: {{ label: function(c) {{ return c.label + ": " + c.parsed + " trades"; }} }} }}
      }},
      cutout: "65%",
      onClick: function(e, el) {{
        if (!el.length) return;
        var idx = el[0].index;
        var label = idx === 0 ? "Wins" : "Losses";
        var filtered = allPnl.filter(function(r) {{ return idx === 0 ? r.pnl_usd > 0 : r.pnl_usd <= 0; }});
        var rows = filtered.map(function(r) {{
          var c = r.pnl_usd >= 0 ? "#00c896" : "#ff4d6d";
          var p = r.pnl_usd >= 0 ? "+" : "";
          return "<tr><td style='padding:6px 10px'><b>" + r.symbol + "</b></td><td style='padding:6px 10px;color:" + c + "'>" + p + "$" + r.pnl_usd.toFixed(2) + "</td><td style='padding:6px 10px;color:" + c + "'>" + p + r.pnl_pct.toFixed(2) + "%</td><td style='padding:6px 10px;color:#4a6080'>" + r.exit_ts + "</td></tr>";
        }}).join("");
        showModal("<div style='font-size:14px;font-weight:800;color:#fff;margin-bottom:16px'>" + label + " (" + filtered.length + " trades)</div><table style='width:100%;border-collapse:collapse;font-family:Courier,monospace;font-size:12px'><thead><tr><th style='padding:6px 10px;color:#4a6080;text-align:left'>Symbol</th><th style='padding:6px 10px;color:#4a6080;text-align:left'>P&L $</th><th style='padding:6px 10px;color:#4a6080;text-align:left'>P&L %</th><th style='padding:6px 10px;color:#4a6080;text-align:left'>Closed</th></tr></thead><tbody>" + rows + "</tbody></table>");
      }}
    }}
  }});

  // ── Bar — Position detail popup ──
  var barChart = new Chart(document.getElementById("barChart"), {{
    type: "bar",
    data: {{ labels: barLabels, datasets: [{{ data: barValues, backgroundColor: barColors, borderRadius: 4, hoverBackgroundColor: barColors.map(function(c) {{ return c + "cc"; }}) }}] }},
    options: {{
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{
          label: function(c) {{
            var p = posData[c.dataIndex];
            if (!p) return "";
            var sign = c.parsed.y >= 0 ? "+" : "";
            return [
              "Unrealized: " + sign + "$" + c.parsed.y.toFixed(2),
              "Entry: $" + p.entry_price,
              "Current: $" + (p.current_price ? p.current_price.toFixed(3) : "N/A"),
              "Stop: $" + p.stop_loss + "  TP: $" + p.take_profit
            ];
          }}
        }} }}
      }},
      scales: {{
        x: {{ ticks: {{ color:"#4a6080",font:{{size:9}} }}, grid:{{color:"#1e2d4a"}} }},
        y: {{ ticks: {{ color:"#4a6080",font:{{size:9}} }}, grid:{{color:"#1e2d4a"}} }}
      }},
      onClick: function(e, el) {{
        if (!el.length) return;
        var p = posData[el[0].index];
        if (!p) return;
        var c = p.unrealized_pnl >= 0 ? "#00c896" : "#ff4d6d";
        var sign = p.unrealized_pnl >= 0 ? "+" : "";
        var ac = p.action === "BUY" ? "#00c896" : "#ff4d6d";
        showModal(
          "<div style='font-size:18px;font-weight:800;color:#fff;margin-bottom:4px'>" + p.symbol + "</div>" +
          "<span style='background:" + ac + "22;color:" + ac + ";padding:2px 8px;border-radius:3px;font-size:11px;font-weight:700'>" + p.action + "</span>" +
          "<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:20px'>" +
          "<div style='background:#162038;border-radius:8px;padding:14px'><div style='font-size:10px;color:#4a6080;margin-bottom:4px'>ENTRY PRICE</div><div style='font-size:20px;font-weight:800'>$" + p.entry_price + "</div></div>" +
          "<div style='background:#162038;border-radius:8px;padding:14px'><div style='font-size:10px;color:#4a6080;margin-bottom:4px'>CURRENT PRICE</div><div style='font-size:20px;font-weight:800;color:" + c + "'>" + (p.current_price ? "$" + p.current_price.toFixed(3) : "N/A") + "</div></div>" +
          "<div style='background:#162038;border-radius:8px;padding:14px'><div style='font-size:10px;color:#4a6080;margin-bottom:4px'>UNREALIZED P&L</div><div style='font-size:20px;font-weight:800;color:" + c + "'>" + sign + "$" + (p.unrealized_pnl ? p.unrealized_pnl.toFixed(2) : "0") + "</div></div>" +
          "<div style='background:#162038;border-radius:8px;padding:14px'><div style='font-size:10px;color:#4a6080;margin-bottom:4px'>QUANTITY</div><div style='font-size:20px;font-weight:800'>" + p.quantity + " shares</div></div>" +
          "<div style='background:#162038;border-radius:8px;padding:14px'><div style='font-size:10px;color:#4a6080;margin-bottom:4px'>STOP LOSS</div><div style='font-size:20px;font-weight:800;color:#ff4d6d'>$" + p.stop_loss + "</div></div>" +
          "<div style='background:#162038;border-radius:8px;padding:14px'><div style='font-size:10px;color:#4a6080;margin-bottom:4px'>TAKE PROFIT</div><div style='font-size:20px;font-weight:800;color:#00c896'>$" + p.take_profit + "</div></div>" +
          "</div>" +
          "<div style='margin-top:16px;font-size:11px;color:#4a6080'>Opened: " + p.entry_ts + "</div>"
        );
      }}
    }}
  }});

  // ── Line — Trade detail on click ──
  var lineChart = new Chart(document.getElementById("lineChart"), {{
    type: "line",
    data: {{ labels: lineLabels, datasets: [{{ data: lineValues, borderColor: lineColor, backgroundColor: lineColor+"18", fill: true, tension: 0.3, pointRadius: 5, pointHoverRadius: 8, borderWidth: 2, pointBackgroundColor: lineColor }}] }},
    options: {{
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{
          title: function(c) {{ return "Date: " + c[0].label; }},
          label: function(c) {{
            var idx = c.dataIndex;
            var trade = pnlData[idx];
            if (!trade) return "Cumulative: $" + c.parsed.y.toFixed(2);
            var sign = trade.pnl_usd >= 0 ? "+" : "";
            return [
              "Cumulative P&L: $" + c.parsed.y.toFixed(2),
              "Trade: " + trade.symbol + " " + sign + "$" + trade.pnl_usd.toFixed(2) + " (" + sign + trade.pnl_pct.toFixed(2) + "%)"
            ];
          }}
        }} }}
      }},
      scales: {{
        x: {{ ticks: {{ color:"#4a6080",font:{{size:9}},maxTicksLimit:6 }}, grid:{{color:"#1e2d4a"}} }},
        y: {{ ticks: {{ color:"#4a6080",font:{{size:9}} }}, grid:{{color:"#1e2d4a"}} }}
      }},
      onClick: function(e, el) {{
        if (!el.length) return;
        var idx = el[0].index;
        var trade = pnlData[idx];
        if (!trade) return;
        var c = trade.pnl_usd >= 0 ? "#00c896" : "#ff4d6d";
        var sign = trade.pnl_usd >= 0 ? "+" : "";
        showModal(
          "<div style='font-size:14px;font-weight:800;color:#fff;margin-bottom:16px'>Trade Detail</div>" +
          "<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>" +
          "<div style='background:#162038;border-radius:8px;padding:14px'><div style='font-size:10px;color:#4a6080;margin-bottom:4px'>SYMBOL</div><div style='font-size:22px;font-weight:800'>" + trade.symbol + "</div></div>" +
          "<div style='background:#162038;border-radius:8px;padding:14px'><div style='font-size:10px;color:#4a6080;margin-bottom:4px'>P&L</div><div style='font-size:22px;font-weight:800;color:" + c + "'>" + sign + "$" + trade.pnl_usd.toFixed(2) + "</div></div>" +
          "<div style='background:#162038;border-radius:8px;padding:14px'><div style='font-size:10px;color:#4a6080;margin-bottom:4px'>P&L %</div><div style='font-size:22px;font-weight:800;color:" + c + "'>" + sign + trade.pnl_pct.toFixed(2) + "%</div></div>" +
          "<div style='background:#162038;border-radius:8px;padding:14px'><div style='font-size:10px;color:#4a6080;margin-bottom:4px'>CUMULATIVE</div><div style='font-size:22px;font-weight:800'>$" + trade.cumulative.toFixed(2) + "</div></div>" +
          "</div>" +
          "<div style='margin-top:16px;font-size:11px;color:#4a6080'>Closed: " + trade.exit_date + "</div>"
        );
      }}
    }}
  }});

  // Close modal on background click
  document.getElementById("modal").addEventListener("click", function(e) {{
    if (e.target === this) this.style.display = "none";
  }});
}})();
</script>
<script>
(function() {{
  var s = sessionStorage.getItem('scrollY');
  if (s) {{ window.scrollTo(0, parseInt(s, 10)); sessionStorage.removeItem('scrollY'); }}
  window.addEventListener('beforeunload', function() {{ sessionStorage.setItem('scrollY', window.scrollY); }});
  setInterval(function() {{
    if (document.visibilityState === 'visible') {{ location.reload(); }}
  }}, 360000);
}})();
</script>
</body></html>"""

    Path(OUTPUT).write_text(html)
    print(f"\nDashboard saved! Opening in browser...")
    webbrowser.open("file://" + os.path.abspath(OUTPUT))

if __name__ == "__main__":
    main()
