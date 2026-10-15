#!/bin/bash
# Stop the background equity dashboard server.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

PORT=8080
EXISTING_PID="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
if [[ -n "$EXISTING_PID" ]]; then
  kill -9 $EXISTING_PID 2>/dev/null || true
  echo "Stopped equity dashboard (pid $EXISTING_PID)"
else
  echo "Equity dashboard was not running."
fi
rm -f "$REPO/config/.dashboard_pid"
