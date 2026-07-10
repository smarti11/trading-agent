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

TS_IP="$(tailscale ip -4 2>/dev/null || true)"
PORT=8081
echo ""
echo "============================================================"
echo "  OPTIONS DASHBOARD"
echo "  Local:     http://localhost:${PORT}/options_dashboard.html"
if [[ -n "$TS_IP" ]]; then
  echo "  Tailscale: http://${TS_IP}:${PORT}/options_dashboard.html"
fi
echo "  Press Ctrl+C to stop the server"
echo "============================================================"
echo ""

python3 -m http.server "$PORT" --bind 0.0.0.0
