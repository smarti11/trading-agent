#!/bin/bash
# Serve options dashboard on first free port in 9080-9099.
# Does not touch racing (8081) or other agents. Binds 0.0.0.0 for Tailscale.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

if [[ -d venv ]]; then
  source venv/bin/activate
fi

PORT_START=9080
PORT_END=9099
if [[ -f config/options_settings.py ]]; then
  read -r PORT_START PORT_END < <(python3 - <<'PY'
from config.options_settings import OPTIONS_DASHBOARD_PORT_START, OPTIONS_DASHBOARD_PORT_END
print(OPTIONS_DASHBOARD_PORT_START, OPTIONS_DASHBOARD_PORT_END)
PY
)
fi

echo "Building options dashboard..."
python3 options_dashboard.py

find_port() {
  local port pid cwd
  for port in $(seq "$PORT_START" "$PORT_END"); do
    if ! lsof -ti tcp:"$port" >/dev/null 2>&1; then
      echo "$port"
      return 0
    fi
    pid=$(lsof -ti tcp:"$port" 2>/dev/null | head -1)
    [[ -z "$pid" ]] && continue
    cwd=$(lsof -p "$pid" 2>/dev/null | awk '/cwd/{print $NF}')
    if [[ "$cwd" == *trading-agent* ]]; then
      echo "Stopping old options dashboard on port $port (pid $pid)..." >&2
      kill "$pid" 2>/dev/null || true
      sleep 1
      if ! lsof -ti tcp:"$port" >/dev/null 2>&1; then
        echo "$port"
        return 0
      fi
    fi
  done
  return 1
}

PORT="$(find_port)" || {
  echo "ERROR: No free port in ${PORT_START}-${PORT_END}."
  echo "Check: lsof -i -P -n | grep LISTEN | grep Python"
  exit 1
}

TS_IP="$(tailscale ip -4 2>/dev/null || true)"
echo ""
echo "============================================================"
echo "  OPTIONS DASHBOARD"
echo "  Local:     http://localhost:${PORT}/options_dashboard.html"
if [[ -n "$TS_IP" ]]; then
  echo "  Tailscale: http://${TS_IP}:${PORT}/options_dashboard.html"
fi
echo "  (Port ${PORT} — racing uses 8081, insider uses 8083)"
echo "  Press Ctrl+C to stop"
echo "============================================================"
echo ""

exec python3 -m http.server "$PORT" --bind 0.0.0.0
