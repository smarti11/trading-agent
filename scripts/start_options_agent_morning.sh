#!/bin/bash
# Start options agent for the trading day (idempotent).
# Safe for Desktop double-click or launchd weekday morning schedule.
set -euo pipefail

REPO="${TRADING_AGENT_HOME:-$HOME/agents/trading-agent}"
cd "$REPO" || exit 1
mkdir -p logs

notify() {
  local title="$1" msg="$2"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$msg\" with title \"$title\""
  fi
}

if pgrep -f "python.*options_agent.py" >/dev/null 2>&1; then
  echo "Options agent already running."
  notify "Options Agent" "Already running — no action needed."
  exit 0
fi

if [[ -d venv ]]; then
  # shellcheck source=/dev/null
  source venv/bin/activate
fi

# Stale token from a previous calendar day → clear so OAuth starts cleanly
TOKEN_FILE="config/.etrade_token.json"
if [[ -f "$TOKEN_FILE" ]]; then
  token_date=$(python3 -c "import json; print(json.load(open('$TOKEN_FILE')).get('date',''))" 2>/dev/null || true)
  today=$(date +%Y-%m-%d)
  if [[ -n "$token_date" && "$token_date" != "$today" ]]; then
    echo "E*Trade token from $token_date expired — clearing for re-auth."
    rm -f "$TOKEN_FILE"
  fi
fi

notify "Options Agent" "Starting — complete E*Trade auth if a browser opens."
echo "Starting options agent at $(date)"
echo "Log: $REPO/logs/options_agent.log"

# Run detached so launchd / Terminal can exit; agent keeps scanning
nohup python3 options_agent.py >>logs/options_agent_stdout.log 2>&1 &
AGENT_PID=$!
echo "$AGENT_PID" > config/.options_agent.pid
sleep 2

if kill -0 "$AGENT_PID" 2>/dev/null; then
  echo "Options agent started (pid $AGENT_PID)."
  notify "Options Agent" "Running (pid $AGENT_PID). Check Terminal/log if auth is needed."
else
  echo "ERROR: agent failed to start — see logs/options_agent_stdout.log"
  notify "Options Agent" "Failed to start — check logs."
  exit 1
fi

# If auth pending, surface the URL
for _ in 1 2 3 4 5 6; do
  if [[ -f config/.etrade_auth_pending ]]; then
    auth_url=$(python3 -c "import json; print(json.load(open('config/.etrade_auth_pending'))['auth_url'])" 2>/dev/null || true)
    if [[ -n "$auth_url" ]]; then
      echo "E*TRADE AUTH REQUIRED:"
      echo "  $auth_url"
      echo "  Then: echo CODE > $REPO/config/.etrade_verifier"
      notify "Options Agent — Auth Needed" "Open E*Trade link and paste verifier (see Terminal/log)."
      if command -v open >/dev/null 2>&1; then
        open "$auth_url"
      fi
    fi
    break
  fi
  sleep 2
done
