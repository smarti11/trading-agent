#!/bin/bash
# Install weekday 9:00 AM auto-start for the options agent.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
USER_PLIST="${HOME}/Library/LaunchAgents/com.optionsagent.morning.plist"
DESKTOP="${HOME}/Desktop"

chmod +x "$REPO/scripts/start_options_agent_morning.sh"
chmod +x "$REPO/scripts/stop_options_agent.sh"
chmod +x "$REPO/shortcuts/Start Options Agent.command"

cp "$REPO/shortcuts/Start Options Agent.command" "$DESKTOP/"
chmod +x "$DESKTOP/Start Options Agent.command"

cat > "$DESKTOP/Start Options Agent (Background).command" <<EOF
#!/bin/bash
"$REPO/scripts/start_options_agent_morning.sh"
read -r -p "Press Enter to close..."
EOF
chmod +x "$DESKTOP/Start Options Agent (Background).command"

cat > "$DESKTOP/Stop Options Agent.command" <<EOF
#!/bin/bash
"$REPO/scripts/stop_options_agent.sh"
read -r -p "Press Enter to close..."
EOF
chmod +x "$DESKTOP/Stop Options Agent.command"

sed "s|REPO_PATH|$REPO|g" "$REPO/shortcuts/com.optionsagent.morning.plist" > "$USER_PLIST"

launchctl bootout "gui/$(id -u)/com.optionsagent.morning" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$USER_PLIST"
launchctl enable "gui/$(id -u)/com.optionsagent.morning" 2>/dev/null || true

echo ""
echo "Installed weekday morning auto-start (Mon–Fri 9:00 AM local)."
echo "  Plist: $USER_PLIST"
echo ""
echo "IMPORTANT:"
echo "  1. Set Mac mini timezone to Eastern (System Settings → Date & Time)"
echo "  2. When notified Auth Needed, open the E*Trade link and run:"
echo "       echo YOUR_CODE > $REPO/config/.etrade_verifier"
echo ""
echo "Desktop shortcuts:"
echo "  • Start Options Agent.command              (interactive Terminal)"
echo "  • Start Options Agent (Background).command"
echo "  • Stop Options Agent.command"
echo ""
echo "Test now (optional):"
echo "  $REPO/scripts/start_options_agent_morning.sh"
