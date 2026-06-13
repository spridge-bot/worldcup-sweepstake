#!/bin/zsh
# Continuous live publisher for the Mac mini.
# Publishes the churning live data (data.json / sofascore.json / details.json /
# img) to the *live-data* branch — which GitHub Pages does NOT build from — so
# the Pages site (index.html on main) stays stable and never thrashes. The page
# reads data from raw.githubusercontent on live-data, which is fresh per commit.
# Cadence is kickoff-aware: tight while live, tightening as each start time nears.
# Runs in a dedicated worktree; KeepAlive launchd restarts it if it ever dies.
set -u
WORKTREE="/Users/ianspridgeon/wc-live"
cd "$WORKTREE" || exit 1
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PITCH_PYTHON="/Users/ianspridgeon/worldcup-sweepstake/.venv-pitch/bin/python"

is_live() {
  /usr/bin/python3 -c 'import json,sys; sys.exit(0 if json.load(open("docs/data.json")).get("live") else 1)' 2>/dev/null
}

while true; do
  # keep this branch's code/draw in lock-step with main, then regenerate data
  git fetch -q origin main 2>/dev/null
  git checkout -q origin/main -- scripts data docs/index.html docs/draw.html 2>/dev/null

  /usr/bin/python3 scripts/update_scores.py  >/dev/null 2>&1
  /usr/bin/python3 scripts/sofascore_live.py >/dev/null 2>&1

  git add -A docs scripts data 2>/dev/null
  if ! git diff --cached --quiet 2>/dev/null; then
    git commit -q -m "live data $(date -u '+%FT%TZ')" >/dev/null 2>&1
    git push -q origin live-data >/dev/null 2>&1 || {
      git pull --rebase -X ours --autostash origin live-data >/dev/null 2>&1
      git push -q origin live-data >/dev/null 2>&1
    }
    echo "[$(date -u '+%FT%TZ')] pushed live-data ($(is_live && echo live || echo idle))"
  fi

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
            s = (datetime.fromisoformat(u["utc"].replace("Z", "+00:00")) - now).total_seconds()
            if s > -300:
                secs.append(s)
        except Exception:
            pass
    print(300 if not secs else (10 if min(secs) <= 180 else min(int(min(secs) - 120), 300)))
except Exception:
    print(60)
PY
)
    sleep "${nap:-60}"
  fi
done
