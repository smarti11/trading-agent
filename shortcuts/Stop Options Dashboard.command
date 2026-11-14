#!/bin/bash
# Double-click: stop background options dashboard.
set -euo pipefail

REPO="${TRADING_AGENT_HOME:-$HOME/agents/trading-agent}"
"$REPO/scripts/stop_options_dashboard.sh"

if command -v osascript >/dev/null 2>&1; then
  osascript -e 'display notification "Options dashboard server stopped" with title "Options Dashboard"'
fi

read -r -p "Press Enter to close..."
