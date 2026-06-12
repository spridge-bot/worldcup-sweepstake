#!/bin/zsh
# Mac mini updater: refresh scores, and during matches run the fast watcher
# locally so live coverage (and the public relay) survives the iMac sleeping.
# Pitch images can't render here (needs Python >= 3.10) — the iMac fills those
# in whenever it's awake; everything else degrades gracefully.
set -u
cd "$(dirname "$0")/.."
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"

/usr/bin/python3 scripts/update_scores.py 2>&1 | tail -2

if /usr/bin/python3 -c 'import json,sys; sys.exit(0 if json.load(open("docs/data.json")).get("live") else 1)' \
   && ! pgrep -f "sofascore_live.py --watch" >/dev/null; then
  mkdir -p logs
  nohup /usr/bin/python3 scripts/sofascore_live.py --watch 25 >> logs/watch.log 2>&1 &
  echo "started live watcher (mini)"
fi
