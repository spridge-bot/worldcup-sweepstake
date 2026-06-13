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

  # cadence: tight while live, and tighten automatically as the next kick-off
  # nears so a starting match is picked up within seconds, not the idle gap
  if is_live; then
    sleep 18
  else
    nap=$(/usr/bin/python3 - <<'PY'
import json
from datetime import datetime, timezone
try:
    d = json.load(open("docs/data.json"))
    now = datetime.now(timezone.utc)
    secs = []
    for u in d.get("upcoming") or []:
        try:
            k = datetime.fromisoformat(u["utc"].replace("Z", "+00:00"))
            s = (k - now).total_seconds()
            if s > -300:                 # future, plus just-passed (catch ESPN lag at KO)
                secs.append(s)
        except Exception:
            pass
    if not secs:
        print(300)                       # nothing imminent -> relaxed idle
    else:
        s = min(secs)
        print(10 if s <= 180 else min(int(s - 120), 300))  # poll hard near KO; else wake ~2m before
except Exception:
    print(60)
PY
)
    sleep "${nap:-60}"
  fi
done
