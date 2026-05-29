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
4. Add your keys to `config/settings.py`

### 2. Install Python dependencies
```bash
cd ~/trading-agent
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
| TRADE_AMOUNT_USD     | $100    | Fixed size per trade           |
| STOP_LOSS_PCT        | 3%      | Auto exit on loss              |
| TAKE_PROFIT_PCT      | 5%      | Auto exit on gain              |
| MAX_OPEN_POSITIONS   | 5       | Max concurrent trades          |
| MAX_DAILY_LOSS_USD   | $300    | Agent pauses if hit            |
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
        <string>/Users/YOUR_USERNAME/trading-agent/venv/bin/python</string>
        <string>/Users/YOUR_USERNAME/trading-agent/agent.py</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>/Users/YOUR_USERNAME/trading-agent/logs/stdout.log</string>
    <key>StandardErrorPath</key><string>/Users/YOUR_USERNAME/trading-agent/logs/stderr.log</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.tradingagent.plist
```
