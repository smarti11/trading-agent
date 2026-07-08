#!/bin/bash
# Install macOS desktop shortcuts for the options agent.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="${HOME}/Desktop"
SHORTCUTS_DIR="${REPO}/shortcuts"

install_one() {
  local name="$1"
  local src="${SHORTCUTS_DIR}/${name}"
  local dest="${DESKTOP}/${name}"

  if [[ ! -f "$src" ]]; then
    echo "Missing: $src"
    exit 1
  fi

  cp "$src" "$dest"
  chmod +x "$dest"
  echo "Installed: $dest"
}

echo "Installing options shortcuts to: $DESKTOP"
echo "Repo: $REPO"
echo ""

install_one "Start Options Agent.command"
install_one "Start Options Dashboard.command"

echo ""
echo "Done. Double-click these on your Desktop:"
echo "  • Start Options Agent.command"
echo "  • Start Options Dashboard.command"
echo ""
echo "First launch tip: if macOS blocks the script, right-click → Open."
