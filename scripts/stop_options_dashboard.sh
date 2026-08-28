#!/bin/bash
# Stop the background options dashboard server.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=options_dashboard_lib.sh
source "$SCRIPT_DIR/options_dashboard_lib.sh"

REPO="$(options_dashboard_repo)"
options_dashboard_stop_existing "$REPO"
rm -f "$REPO/$OPTIONS_DASHBOARD_PORT_FILE"
echo "Options dashboard stopped."
