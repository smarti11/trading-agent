#!/bin/bash
# Double-click launcher for the options dashboard (macOS).
set -euo pipefail

REPO="${TRADING_AGENT_HOME:-$HOME/agents/trading-agent}"
PORT=8081

cd "$REPO" || { echo "ERROR: folder not found: $REPO"; read -r -p "Press Enter to close..."; exit 1; }

if [[ -d venv ]]; then
  source venv/bin/activate
fi

free_port() {
  local pids
  pids=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo ""
  echo "Port $PORT is already in use:"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
  echo ""
  echo "Stopping old server on port $PORT..."
  kill $pids 2>/dev/null || true
  sleep 1
  if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
    echo "ERROR: Could not free port $PORT. Close the other app manually."
    read -r -p "Press Enter to close..."
    exit 1
  fi
}

echo "Building options dashboard..."
python3 options_dashboard.py

free_port

TS_IP="$(tailscale ip -4 2>/dev/null || true)"
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

exec python3 -m http.server "$PORT" --bind 0.0.0.0
