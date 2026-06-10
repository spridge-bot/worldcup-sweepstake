#!/bin/bash
# Double-click to launch the sweepstake page locally.
cd "$(dirname "$0")"
PORT=8123

# Refresh scores first if an API token is available (otherwise just show current data)
if [ -n "$FOOTBALL_DATA_TOKEN" ]; then
  echo "Refreshing live scores..."
  python3 scripts/update_scores.py || true
fi

if lsof -i :$PORT >/dev/null 2>&1; then
  # Server already running from a previous launch — just open the page
  open "http://localhost:$PORT"
else
  (sleep 1 && open "http://localhost:$PORT") &
  echo "Sweepstake running at http://localhost:$PORT"
  echo "Close this window (or press Ctrl+C) to stop."
  python3 -m http.server -d docs $PORT
fi
