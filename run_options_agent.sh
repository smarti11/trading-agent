#!/usr/bin/env bash
# Run the options trading agent inside the project venv.
set -euo pipefail
cd "$(dirname "$0")"
if [[ -d venv ]]; then
  source venv/bin/activate
fi
exec python3 options_agent.py "$@"
