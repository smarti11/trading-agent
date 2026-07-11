#!/bin/bash
# Double-click: start options dashboard in background, then exit.
set -euo pipefail

REPO="${TRADING_AGENT_HOME:-$HOME/agents/trading-agent}"
exec "$REPO/scripts/start_options_dashboard_background.sh"
