#!/bin/bash
# Serve equity dashboard on port 8080. Binds 0.0.0.0 for Tailscale/LAN.
REPO="${TRADING_AGENT_HOME:-$HOME/agents/trading-agent}"
cd "$REPO" || exit 1

if [[ -d venv ]]; then
  PYTHON="$REPO/venv/bin/python3"
else
  PYTHON="python3"
fi

TS_IP="$(tailscale ip -4 2>/dev/null || true)"
echo ""
echo "============================================================"
echo "  EQUITY DASHBOARD"
echo "  Local:   http://localhost:8080/dashboard.html"
if [[ -n "$TS_IP" ]]; then
  echo "  Tailscale: http://${TS_IP}:8080/dashboard.html"
fi
echo "  Press Ctrl+C to stop"
echo "============================================================"
echo ""

exec "$PYTHON" -m http.server 8080 --bind 0.0.0.0
