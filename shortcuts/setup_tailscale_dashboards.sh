#!/bin/bash
# Configure Mac mini dashboards for Tailscale access from phone/other devices.
set -euo pipefail

echo "=== Tailscale dashboard setup ==="
echo ""

if ! command -v tailscale >/dev/null 2>&1; then
  echo "Tailscale is not installed."
  echo "Install: https://tailscale.com/download/mac"
  echo "Or: brew install --cask tailscale"
  exit 1
fi

if ! tailscale status >/dev/null 2>&1; then
  echo "Tailscale is installed but not connected."
  echo "Open the Tailscale app and sign in, then run this script again."
  exit 1
fi

TS_IP="$(tailscale ip -4)"
HOSTNAME="$(tailscale status --json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
self=d.get('Self',{})
print(self.get('DNSName','').rstrip('.'))
" 2>/dev/null || true)"

echo "Tailscale IP:  $TS_IP"
[[ -n "$HOSTNAME" ]] && echo "MagicDNS:    $HOSTNAME"
echo ""
echo "Bookmark these on your phone (Tailscale app must be ON):"
echo ""
echo "  Options:  http://${TS_IP}:8081/options_dashboard.html"
echo "  Equity:   http://${TS_IP}:8080/dashboard.html"
if [[ -n "$HOSTNAME" ]]; then
  echo ""
  echo "  (MagicDNS, if enabled in Tailscale admin):"
  echo "  Options:  http://${HOSTNAME}:8081/options_dashboard.html"
  echo "  Equity:   http://${HOSTNAME}:8080/dashboard.html"
fi
echo ""
echo "--- macOS Firewall ---"
echo "If the phone cannot connect, allow incoming connections:"
echo "  System Settings → Network → Firewall → Options"
echo "  • Allow built-in software to receive connections"
echo "  • Or add Python / Terminal to allowed apps"
echo ""
echo "--- Start dashboard servers ---"
echo "On the Mac mini, run (or use Desktop shortcuts):"
echo "  ./serve_options_dashboard.sh   # port 8081"
echo "  ./serve_dashboard.sh           # port 8080"
echo ""
echo "Servers bind to 0.0.0.0 so Tailscale peers can reach them."
echo ""
echo "Optional — Tailscale Serve (HTTPS within your tailnet only):"
echo "  tailscale serve --bg --https=8443 http://127.0.0.1:8081"
echo "  Then open: https://$(hostname -s 2>/dev/null || echo 'your-mac').<tailnet>:8443/options_dashboard.html"
echo ""
echo "Done."
