#!/bin/bash
# Install background options dashboard (Desktop shortcuts + optional launchd auto-start).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="${HOME}/Desktop"
USER_PLIST="${HOME}/Library/LaunchAgents/com.optionsdashboard.plist"

install_shortcut() {
  local name="$1"
  cp "$REPO/shortcuts/$name" "$DESKTOP/$name"
  chmod +x "$DESKTOP/$name"
  echo "Installed: $DESKTOP/$name"
}

echo "Repo: $REPO"
echo ""

chmod +x "$REPO/scripts/"*.sh

install_shortcut "Start Options Dashboard.command"
install_shortcut "Stop Options Dashboard.command"

read -r -p "Auto-start dashboard on Mac login? [y/N] " autostart
if [[ "${autostart,,}" == "y" ]]; then
  sed "s|REPO_PATH|$REPO|g" "$REPO/shortcuts/com.optionsdashboard.plist" > "$USER_PLIST"
  launchctl bootout "gui/$(id -u)/com.optionsdashboard" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$USER_PLIST"
  echo "Installed launchd agent: $USER_PLIST"
else
  echo "Skipped launchd auto-start."
fi

echo ""
echo "Done."
echo "  Start (background): double-click Start Options Dashboard.command"
echo "  Stop:               double-click Stop Options Dashboard.command"
echo "  Phone URL:          check config/.options_dashboard_port after starting"
