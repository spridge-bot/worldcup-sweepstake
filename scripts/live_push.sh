#!/bin/zsh
# Live update orchestrator (runs on the iMac via launchd every 5 minutes).
#  1. pull latest (GitHub Actions also commits data on its own cron)
#  2. refresh scores (ESPN) + Sofascore live layer (incidents/line-ups/pitch)
#  3. mirror docs/ to the Mac mini (LAN site)
#  4. push to GitHub so the public Pages site stays fresh
# Every step fails soft so one hiccup doesn't kill the chain.
set -u
cd "$(dirname "$0")/.."
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

echo "=== live_push $(date '+%F %T') ==="

# schedule-aware: full updates only around matches (from 10 min before any
# kick-off until ~15 min after full-time), plus an hourly heartbeat so the
# site never goes completely stale. No matches = no churn, no noisy commits.
ACTIVE=$(/usr/bin/python3 - <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
try:
    d = json.load(open("docs/data.json"))
except Exception:
    print("yes"); sys.exit()
now = datetime.now(timezone.utc)
if d.get("live"):
    print("yes"); sys.exit()
stale = True
try:
    gen = datetime.fromisoformat(d["generated_at"].replace("Z", "+00:00"))
    stale = (now - gen) > timedelta(minutes=65)
except Exception:
    pass
kicks = []
for r in (d.get("upcoming") or []) + (d.get("results") or []):
    try:
        kicks.append(datetime.fromisoformat(r["utc"].replace("Z", "+00:00")))
    except Exception:
        pass
in_window = any(k - timedelta(minutes=10) <= now <= k + timedelta(minutes=165)
                for k in kicks)
print("yes" if (in_window or stale) else "no")
PY
)
if [ "$ACTIVE" != "yes" ]; then
  echo "outside match window — sleeping until the next game"
  exit 0
fi

git pull --rebase --autostash -X theirs origin main 2>&1 | tail -1 \
  || { git rebase --abort 2>/dev/null; git reset --hard origin/main; }

/usr/bin/python3 scripts/update_scores.py 2>&1 | tail -2
/usr/bin/python3 scripts/sofascore_live.py 2>&1 | grep -vE "NotOpenSSL|warnings.warn" | tail -3

# while matches are in play, run the fast watcher (~25s refresh); it exits at FT
if /usr/bin/python3 -c 'import json,sys; sys.exit(0 if json.load(open("docs/data.json")).get("live") else 1)' \
   && ! pgrep -f "sofascore_live.py --watch" >/dev/null; then
  mkdir -p logs
  nohup /usr/bin/python3 scripts/sofascore_live.py --watch 20 >> logs/watch.log 2>&1 &
  echo "started live watcher"
fi

rsync -a --delete --exclude '.DS_Store' --exclude '*.tmp' --exclude 'logs' --exclude 'var' \
      --exclude '.venv-pitch' --exclude 'output' ./ macmini:worldcup-sweepstake/ \
  && echo "rsync -> macmini OK" || echo "rsync -> macmini FAILED (is it on?)"

git add docs/data.json docs/details.json docs/sofascore.json docs/img 2>/dev/null
if ! git diff --cached --quiet; then
  git commit -q -m "Live update $(date -u '+%FT%TZ')"
  git push -q origin main 2>&1 | tail -1 \
    || { git pull --rebase -X theirs origin main && git push -q origin main; }
  echo "pushed to GitHub"
else
  echo "no data changes"
fi
