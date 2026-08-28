# Trading Agent — Mean Reversion
## Mac mini | E*Trade | Stocks + ETFs | Paper → Live

---

## Architecture

```
trading-agent/
├── agent.py              ← Main entry point (run this)
├── requirements.txt
├── config/
│   └── settings.py       ← All configuration here
├── core/
│   ├── signals.py        ← RSI + Bollinger + Z-score engine
│   └── risk.py           ← Stop loss, take profit, daily limits
├── data/
│   └── fetcher.py        ← Most active stocks + price history
├── broker/
│   └── etrade.py         ← E*Trade OAuth + order placement
├── db/
│   └── database.py       ← SQLite trade log + P&L tracker
└── logs/
    └── agent.log
```

---

## Setup (Mac mini)

### 1. Get E*Trade API Access
1. Go to https://developer.etrade.com/getting-started
2. Create a developer account and register an application
3. You'll receive **two sets** of keys:
   - **Sandbox** keys (paper trading) → use these first
   - **Production** keys (live trading) → use only when ready
4. Add your keys via environment variables (recommended) or `config/settings.py`:
```bash
export ETRADE_SANDBOX_KEY=your_sandbox_key
export ETRADE_SANDBOX_SECRET=your_sandbox_secret
```

### 2. Install Python dependencies
```bash
cd ~/agents/trading-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Run in Paper Mode (default)
```bash
python agent.py
```
On first run, a browser will open asking you to authorize the E*Trade app.
Paste the verifier code shown. Token is saved for the rest of the day.

### 4. Single scan (good for testing)
```bash
python agent.py --once
```

### 5. View summary
```bash
python agent.py --summary
```

---

## Paper → Live Transition Checklist

Before going live, confirm ALL of the following:

- [ ] Ran paper mode for at least **2 weeks**
- [ ] Win rate ≥ 50% in paper mode
- [ ] No logic errors in trade log (db/trades.db)
- [ ] Reviewed all stop-loss triggers
- [ ] Set `PAPER_TRADING = False` in `config/settings.py`
- [ ] Replaced sandbox keys with production keys in settings
- [ ] Set a conservative `MAX_DAILY_LOSS_USD` (start with $100)
- [ ] Start with `MAX_OPEN_POSITIONS = 2`

To go live:
```bash
python agent.py --live
```
The agent requires manual confirmation ("YES") before executing real trades.

---

## Signal Logic

A trade fires when **2 of 3** indicators agree on direction:

| Indicator     | BUY trigger              | SELL trigger             |
|---------------|--------------------------|--------------------------|
| RSI (14)      | RSI < 35                 | RSI > 65                 |
| Bollinger (20)| Price touches lower band | Price touches upper band |
| Z-Score (20)  | Z < -1.5                 | Z > +1.5                 |

---

## Risk Parameters (config/settings.py)

| Setting              | Default | Description                    |
|----------------------|---------|--------------------------------|
| TRADE_AMOUNT_USD     | $500    | Fixed size per trade           |
| USE_ATR_STOPS        | True    | ATR-based stop/take when OHLC available |
| ALLOW_SHORTS         | False   | Block SELL-to-open signals     |
| STOP_LOSS_PCT        | 3%      | Fallback reference stop        |
| TAKE_PROFIT_PCT      | 5%      | Fallback take profit           |
| MAX_OPEN_POSITIONS   | 5       | Max concurrent trades          |
| MAX_DAILY_LOSS_USD   | $300    | Agent pauses if hit            |
| AGGREGATE_CB_USD     | $200    | Aggregate unrealized loss halt |
| SCAN_INTERVAL_SEC    | 300     | How often to scan (5 min)      |

---

## Viewing Trade Data

SQLite database at `db/trades.db`. View with:
```bash
sqlite3 db/trades.db "SELECT * FROM trades ORDER BY ts DESC LIMIT 20;"
sqlite3 db/trades.db "SELECT SUM(pnl_usd), COUNT(*) FROM pnl;"
```

Or use a free GUI like **DB Browser for SQLite** (https://sqlitebrowser.org).

---

## Auto-start on Mac mini (optional)

To run the agent automatically when your Mac mini starts:
```bash
# Create a launch agent plist
cat > ~/Library/LaunchAgents/com.tradingagent.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.tradingagent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USERNAME/agents/trading-agent/venv/bin/python</string>
        <string>/Users/YOUR_USERNAME/agents/trading-agent/agent.py</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>/Users/YOUR_USERNAME/agents/trading-agent/logs/stdout.log</string>
    <key>StandardErrorPath</key><string>/Users/YOUR_USERNAME/agents/trading-agent/logs/stderr.log</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.tradingagent.plist
```

---

## Options Trading Agent

A parallel agent for **directional long options** (calls on oversold, puts on overbought) using the same mean-reversion signal engine as the equity agent. It runs independently and does not affect the equity strategy lock in `PATH_C_COMMITMENT.md`.

### Architecture

```
options_agent.py              ← Options entry point
config/options_settings.py    ← Options-specific parameters
core/options/
  ├── chain.py                ← Contract selection + OCC symbols
  ├── signals.py              ← Maps equity signals → calls/puts
  └── risk.py                 ← Premium-based exits, DTE limits
data/options_fetcher.py       ← yfinance option chains
broker/options_orders.py      ← E*Trade OPTN order placement
db/options_database.py        ← Separate SQLite DB (db/options_trades.db)
options_dashboard.py          ← Separate web dashboard (port 8081)
```

### Run in paper mode

```bash
python options_agent.py --once     # single scan (good for testing)
python options_agent.py            # continuous scan loop
python options_agent.py --summary  # P&L summary
```

Or use the shell wrapper:

```bash
chmod +x run_options_agent.sh
./run_options_agent.sh --once
```

### Options strategy (v0.2 trend-dip)

**BULL-only long calls** on dip-and-reclaim — not raw oversold mean-reversion.

| Gate | Rule |
|------|------|
| Regime | SPY **BULL** only |
| Setup | Price above rising 20-MA + RSI dipped &lt; 40 in last 5d |
| Trigger | RSI back ≥ 45 **or** price reclaims MA |
| Contract | Prem ≥ $1, δ ~0.45–0.60, DTE 30–45, spread ≤ 8% |
| Size | Max **$150** risk to stop, max **3** contracts |
| Exits | −35% stop / +70% TP / trail after +40% / time-stop day 5 / 14 DTE |

Puts are disabled until call edge is proven. Equity PATH_C is untouched.

### Live options trading

Requires E*Trade options approval on your account. Set `PAPER_TRADING = False` in `config/settings.py`, then:

```bash
python options_agent.py --live
```

**Note:** yfinance chains are used for paper mode and signal research. For live execution, verify quotes against your broker before relying on fills.

### Options dashboard (separate from equity)

The options agent has its **own** dashboard — it does not modify `dashboard.html`.

```bash
# Generate dashboard HTML
python3 options_dashboard.py

# Serve on port 9080+ (avoids racing on 8081)
chmod +x scripts/serve_options_dashboard.sh serve_options_dashboard.sh
./serve_options_dashboard.sh
```

Then open the URL printed in the terminal (e.g. **http://localhost:9080/options_dashboard.html**).

To auto-rebuild every 5 minutes during market hours (run in a second terminal):

```bash
python3 options_regen_watcher.py
```

| Dashboard | URL | Port |
|-----------|-----|------|
| Equity agent | http://localhost:8080/dashboard.html | 8080 |
| Options agent | http://localhost:9080/options_dashboard.html | 9080+ (auto) |
| Racing agent | (your setup) | 8081 |
| Insider | (your setup) | 8083 |

### Desktop shortcuts (Mac mini)

Install double-click launchers on your Desktop:

```bash
cd ~/agents/trading-agent
git pull origin cursor/options-trading-agent-be09
chmod +x shortcuts/install_options_shortcuts.sh
./shortcuts/install_options_shortcuts.sh
```

This creates:

- **Start Options Agent.command** — runs `options_agent.py` (E*Trade auth when needed)
- **Start Options Dashboard.command** — starts dashboard **in background** (opens browser, no Terminal to keep open)
- **Stop Options Dashboard.command** — stops the background dashboard server

Optional auto-start on Mac login:

```bash
./shortcuts/install_options_dashboard_background.sh
```

After starting, your phone URL uses the port in `config/.options_dashboard_port` (usually 9080).

### Weekday morning auto-start (options agent)

So you don’t forget to start the agent (like a day with zero scans):

```bash
cd ~/agents/trading-agent
git pull origin cursor/options-trading-agent-be09
chmod +x shortcuts/install_options_agent_morning.sh
./shortcuts/install_options_agent_morning.sh
```

This schedules **Mon–Fri 9:00 AM** (Mac local time — set timezone to **Eastern**).

You still must complete **E*Trade auth once per day** when notified (tokens expire at midnight):

```bash
echo YOUR_CODE > ~/agents/trading-agent/config/.etrade_verifier
```

**Tomorrow morning checklist (backup if launchd isn’t installed yet):**

1. By **9:00 AM ET**: double-click **Start Options Agent.command**
2. Paste E*Trade verifier when prompted
3. Confirm: `pgrep -fl options_agent.py` and `tail -f logs/options_agent.log`

### Phone access via Tailscale

`localhost` does not work on your phone. Use your Mac mini **Tailscale IP** instead:

```bash
tailscale ip -4
# e.g. http://100.x.x.x:9080/options_dashboard.html
```

Full setup: [docs/TAILSCALE.md](docs/TAILSCALE.md)

```bash
./shortcuts/setup_tailscale_dashboards.sh
```

Serve scripts bind to `0.0.0.0` so Tailscale peers can connect. Keep Tailscale **on** on your phone.
