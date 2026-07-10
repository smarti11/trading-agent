#!/bin/bash
# Double-click launcher for the options dashboard (macOS).
set -euo pipefail

REPO="${TRADING_AGENT_HOME:-$HOME/agents/trading-agent}"
cd "$REPO" || { echo "ERROR: folder not found: $REPO"; read -r -p "Press Enter to close..."; exit 1; }

exec "$REPO/scripts/serve_options_dashboard.sh"
