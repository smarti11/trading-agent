#!/bin/bash
# Serve options dashboard on first free port in 9080-9099 (see scripts/serve_options_dashboard.sh).
exec "$(dirname "$0")/scripts/serve_options_dashboard.sh"
