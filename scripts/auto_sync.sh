#!/bin/zsh
# Continuous live publisher for the Mac mini.
# Refresh ESPN scores + Sofascore live events, then push to GitHub fast while a
# match is in play (so the public Pages site updates in ~20-30s), backing off
# when nothing is live. KeepAlive launchd restarts it if it ever dies.
set -u
cd "$(dirname "$0")/.."
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

is_live() {
  /usr/bin/python3 -c 'import json,sys; sys.exit(0 if json.load(open("docs/data.json")).get("live") else 1)' 2>/dev/null
}

while true; do
  /usr/bin/python3 scripts/update_scores.py  >/dev/null 2>&1
  /usr/bin/python3 scripts/sofascore_live.py >/dev/null 2>&1

  git add docs/data.json docs/sofascore.json docs/details.json docs/img 2>/dev/null
  if ! git diff --cached --quiet 2>/dev/null; then
    git commit -q -m "live sync $(date -u '+%FT%TZ')" >/dev/null 2>&1
    git push -q origin main >/dev/null 2>&1 || {
      git pull --rebase -X ours --autostash origin main >/dev/null 2>&1
      git push -q origin main >/dev/null 2>&1
    }
    echo "[$(date -u '+%FT%TZ')] pushed ($(is_live && echo live || echo idle))"
  fi

  if is_live; then sleep 18; else sleep 90; fi
done
