#!/bin/bash
# Serve options dashboard on port 8081 (equity dashboard uses 8080).
# Binds 0.0.0.0 so Tailscale and LAN devices can connect.
cd "$(dirname "$0")"
if [[ -d venv ]]; then
  source venv/bin/activate
fi
python3 options_dashboard.py

TS_IP="$(tailscale ip -4 2>/dev/null || true)"
echo ""
echo "============================================================"
echo "  OPTIONS DASHBOARD"
echo "  Local:   http://localhost:8081/options_dashboard.html"
if [[ -n "$TS_IP" ]]; then
  echo "  Tailscale: http://${TS_IP}:8081/options_dashboard.html"
fi
echo "  Press Ctrl+C to stop"
echo "============================================================"
echo ""

exec python3 -m http.server 8081 --bind 0.0.0.0
