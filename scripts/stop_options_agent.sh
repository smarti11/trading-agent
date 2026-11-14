#!/bin/bash
# Stop background options agent started by morning script.
set -euo pipefail

REPO="${TRADING_AGENT_HOME:-$HOME/agents/trading-agent}"
cd "$REPO" || exit 1

stopped=0
if [[ -f config/.options_agent.pid ]]; then
  pid=$(cat config/.options_agent.pid)
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    stopped=1
  fi
  rm -f config/.options_agent.pid
fi

# Fallback: kill by process name
if pgrep -f "python.*options_agent.py" >/dev/null 2>&1; then
  pkill -f "python.*options_agent.py" || true
  stopped=1
fi

if [[ "$stopped" -eq 1 ]]; then
  echo "Options agent stopped."
else
  echo "Options agent was not running."
fi
