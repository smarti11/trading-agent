#!/bin/bash
# Run the trading agent manually using the venv Python.
# From any directory — script resolves its own path.
cd "$(dirname "$0")"
exec venv/bin/python3 agent.py "$@"
