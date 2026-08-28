#!/bin/bash
# Start options dashboard in the background (no Terminal window needed).
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

nohup python3 -m http.server "$PORT" --bind 0.0.0.0 >>"$OPTIONS_DASHBOARD_LOG" 2>&1 &
SERVER_PID=$!
sleep 0.5

if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "ERROR: Dashboard server failed to start. See $OPTIONS_DASHBOARD_LOG"
  exit 1
fi

options_dashboard_save_state "$REPO" "$PORT" "$SERVER_PID"

LOCAL_URL=""
TAILSCALE_URL=""
while IFS= read -r url; do
  if [[ "$url" == http://localhost:* ]]; then
    LOCAL_URL="$url"
  else
    TAILSCALE_URL="$url"
  fi
done < <(options_dashboard_urls "$PORT")

echo "Options dashboard running in background (pid $SERVER_PID, port $PORT)"
echo "  Local:     $LOCAL_URL"
[[ -n "$TAILSCALE_URL" ]] && echo "  Tailscale: $TAILSCALE_URL"
echo "  Log:       $REPO/$OPTIONS_DASHBOARD_LOG"
echo "  Stop:      $REPO/scripts/stop_options_dashboard.sh"

if command -v open >/dev/null 2>&1; then
  open "$LOCAL_URL"
fi

options_dashboard_notify "$LOCAL_URL" "$TAILSCALE_URL"
