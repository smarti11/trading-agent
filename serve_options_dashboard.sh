#!/bin/bash
# Serve options dashboard on port 8081 (equity dashboard uses 8080).
cd "$(dirname "$0")"
if [[ -d venv ]]; then
  source venv/bin/activate
fi
python3 options_dashboard.py
exec python3 -m http.server 8081
