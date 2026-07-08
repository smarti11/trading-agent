#!/bin/bash
# Double-click launcher for the options dashboard (macOS).
set -euo pipefail

REPO="${TRADING_AGENT_HOME:-$HOME/agents/trading-agent}"
cd "$REPO" || { echo "ERROR: folder not found: $REPO"; read -r -p "Press Enter to close..."; exit 1; }

if [[ -d venv ]]; then
  source venv/bin/activate
fi

echo "Building options dashboard..."
python3 options_dashboard.py

PORT=8081
echo ""
echo "============================================================"
echo "  OPTIONS DASHBOARD"
echo "  Open: http://localhost:${PORT}/options_dashboard.html"
echo "  Press Ctrl+C to stop the server"
echo "============================================================"
echo ""

python3 -m http.server "$PORT"
