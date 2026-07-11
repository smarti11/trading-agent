#!/bin/bash
# Shared helpers for options dashboard server scripts.
set -euo pipefail

OPTIONS_DASHBOARD_PID_FILE="config/.options_dashboard.pid"
OPTIONS_DASHBOARD_PORT_FILE="config/.options_dashboard_port"
OPTIONS_DASHBOARD_LOG="logs/options_dashboard_server.log"

options_dashboard_repo() {
  echo "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
}

options_dashboard_activate_venv() {
  local repo="$1"
  if [[ -d "$repo/venv" ]]; then
    # shellcheck source=/dev/null
    source "$repo/venv/bin/activate"
  fi
}

options_dashboard_port_range() {
  local repo="$1"
  local start=9080 end=9099
  if [[ -f "$repo/config/options_settings.py" ]]; then
    read -r start end < <(python3 - <<'PY'
from config.options_settings import OPTIONS_DASHBOARD_PORT_START, OPTIONS_DASHBOARD_PORT_END
print(OPTIONS_DASHBOARD_PORT_START, OPTIONS_DASHBOARD_PORT_END)
PY
)
  fi
  echo "$start $end"
}

options_dashboard_build() {
  local repo="$1"
  echo "Building options dashboard..."
  (cd "$repo" && python3 options_dashboard.py)
}

options_dashboard_find_port() {
  local start="$1" end="$2"
  local port pid cwd
  for port in $(seq "$start" "$end"); do
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

options_dashboard_stop_existing() {
  local repo="$1"
  local pid_file="$repo/$OPTIONS_DASHBOARD_PID_FILE"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      echo "Stopping background options dashboard (pid $pid)..."
      kill "$pid" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$pid_file"
  fi
}

options_dashboard_save_state() {
  local repo="$1" port="$2" pid="$3"
  echo "$port" > "$repo/$OPTIONS_DASHBOARD_PORT_FILE"
  echo "$pid" > "$repo/$OPTIONS_DASHBOARD_PID_FILE"
}

options_dashboard_urls() {
  local port="$1"
  local ts_ip
  ts_ip="$(tailscale ip -4 2>/dev/null || true)"
  echo "http://localhost:${port}/options_dashboard.html"
  if [[ -n "$ts_ip" ]]; then
    echo "http://${ts_ip}:${port}/options_dashboard.html"
  fi
}

options_dashboard_notify() {
  local local_url="$1" tailscale_url="${2:-}"
  local msg="Local: $local_url"
  [[ -n "$tailscale_url" ]] && msg="$msg | Phone: $tailscale_url"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$msg\" with title \"Options Dashboard Running\""
  fi
}
