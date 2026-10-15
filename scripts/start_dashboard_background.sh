#!/bin/bash
# Start the equity dashboard in the background (no Terminal window needed).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO"
mkdir -p logs config

PORT=8080
LOG="$REPO/logs/dashboard_launchd.log"

# Clear out anything already bound to the port (stale process from a previous run/crash)
EXISTING_PID="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
if [[ -n "$EXISTING_PID" ]]; then
  kill -9 $EXISTING_PID 2>/dev/null || true
  sleep 0.5
fi

if [[ -d venv ]]; then
  PYTHON="$REPO/venv/bin/python3"
else
  PYTHON="python3"
fi

nohup "$PYTHON" -m http.server "$PORT" --bind 0.0.0.0 >>"$LOG" 2>&1 &
SERVER_PID=$!
sleep 0.5

if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "$(date): ERROR - dashboard server failed to start" >>"$LOG"
  exit 1
fi

echo "$SERVER_PID" > "$REPO/config/.dashboard_pid"

TS_IP="$(tailscale ip -4 2>/dev/null || true)"
{
  echo "$(date): Equity dashboard running in background (pid $SERVER_PID, port $PORT)"
  echo "  Local:     http://localhost:${PORT}/dashboard.html"
  [[ -n "$TS_IP" ]] && echo "  Tailscale: http://${TS_IP}:${PORT}/dashboard.html"
} >>"$LOG"
