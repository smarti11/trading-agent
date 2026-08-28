#!/bin/bash
# Serve options dashboard in Terminal (foreground). Opens browser.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=options_dashboard_lib.sh
source "$SCRIPT_DIR/options_dashboard_lib.sh"

REPO="$(options_dashboard_repo)"
cd "$REPO"
mkdir -p logs config

options_dashboard_activate_venv "$REPO"
options_dashboard_stop_existing "$REPO"
options_dashboard_build "$REPO"

read -r PORT_START PORT_END < <(options_dashboard_port_range "$REPO")
PORT="$(options_dashboard_find_port "$PORT_START" "$PORT_END")" || {
  echo "ERROR: No free port in ${PORT_START}-${PORT_END}."
  exit 1
}

TS_IP="$(tailscale ip -4 2>/dev/null || true)"
echo ""
echo "============================================================"
echo "  OPTIONS DASHBOARD (foreground)"
echo "  Local:     http://localhost:${PORT}/options_dashboard.html"
if [[ -n "$TS_IP" ]]; then
  echo "  Tailscale: http://${TS_IP}:${PORT}/options_dashboard.html"
fi
echo "  (Port ${PORT} — racing uses 8081, insider uses 8083)"
echo "  Press Ctrl+C to stop"
echo "============================================================"
echo ""

python3 -m http.server "$PORT" --bind 0.0.0.0 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null; exit' EXIT INT TERM

sleep 0.5
if command -v open >/dev/null 2>&1; then
  echo "Opening browser..."
  open "http://localhost:${PORT}/options_dashboard.html"
fi

wait "$SERVER_PID"
