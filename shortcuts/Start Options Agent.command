#!/bin/bash
# Double-click launcher for the options trading agent (macOS).
set -euo pipefail

REPO="${TRADING_AGENT_HOME:-$HOME/agents/trading-agent}"
cd "$REPO" || { echo "ERROR: folder not found: $REPO"; read -r -p "Press Enter to close..."; exit 1; }

if [[ ! -d venv ]]; then
  echo "Creating Python virtual environment..."
  python3 -m venv venv
  source venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
else
  source venv/bin/activate
fi

echo ""
echo "============================================================"
echo "  OPTIONS TRADING AGENT"
echo "  Paper mode · E*Trade auth may be required once per day"
echo "  Press Ctrl+C to stop"
echo "============================================================"
echo ""

python3 options_agent.py

echo ""
read -r -p "Press Enter to close this window..."
