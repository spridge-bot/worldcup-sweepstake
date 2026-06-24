#!/usr/bin/env bash
# Set the World Cup sweepstake up to run on a Mac mini, end to end.
#
#   1. sanity-check Python and do a one-off score refresh
#   2. (optional) create the pitch-graphics venv         (--pitch)
#   3. (optional) install the live Sofascore data path   (--sofascore)
#   4. install + load the launchd jobs so the site self-runs across reboots:
#        com.sweepstake.serve   LAN site on :8123                (always)
#        com.sweepstake.update  ESPN score refresh every 5 min   (always)
#        com.sweepstake.watch   rich live Sofascore layer        (--sofascore)
#
# Re-runnable: it unloads any existing jobs before reloading. Safe to run again
# after a git pull. The committed plists use /Users/ianspridgeon/... paths; this
# rewrites them to wherever the repo actually lives before installing.
#
# Usage:
#   scripts/bootstrap_macmini.sh                 # scores-only (core)
#   scripts/bootstrap_macmini.sh --sofascore     # + live incidents/momentum
#   scripts/bootstrap_macmini.sh --pitch         # + aerial pitch/shot PNGs
#   scripts/bootstrap_macmini.sh --sofascore --pitch
#   scripts/bootstrap_macmini.sh --no-load       # write plists but don't load
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="/usr/bin/python3"
AGENTS="$HOME/Library/LaunchAgents"
DEFAULT_PATH="/Users/ianspridgeon/worldcup-sweepstake"   # path baked into the committed plists

WANT_PITCH=0; WANT_SOFA=0; LOAD=1
for arg in "$@"; do
  case "$arg" in
    --pitch)     WANT_PITCH=1 ;;
    --sofascore) WANT_SOFA=1 ;;
    --no-load)   LOAD=0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

echo "==> repo:   $REPO"
echo "==> python: $($PY --version 2>&1)"
mkdir -p "$REPO/logs" "$AGENTS"

echo "==> one-off score refresh (ESPN, no key needed)"
"$PY" "$REPO/scripts/update_scores.py" 2>&1 | tail -2 || echo "   (refresh failed — will retry on the 5-min timer)"

if [ "$WANT_PITCH" = 1 ]; then
  echo "==> pitch-graphics venv (.venv-pitch: matplotlib + mplsoccer)"
  "$PY" -m venv "$REPO/.venv-pitch"
  "$REPO/.venv-pitch/bin/pip" install --quiet --upgrade pip
  "$REPO/.venv-pitch/bin/pip" install --quiet matplotlib mplsoccer
fi

if [ "$WANT_SOFA" = 1 ]; then
  echo "==> live Sofascore data path (pip3 install datafc)"
  "$PY" -m pip install --quiet datafc || echo "   (datafc install failed — the watch job will exit until it's installed)"
fi

install_job() {  # $1 = label
  local label="$1" src="$REPO/scripts/launchd/$1.plist" dst="$AGENTS/$1.plist"
  [ -f "$src" ] || { echo "   missing $src"; return; }
  # rewrite the baked-in default path to this repo's real location
  sed "s#$DEFAULT_PATH#$REPO#g" "$src" > "$dst"
  echo "   installed $dst"
  if [ "$LOAD" = 1 ]; then
    launchctl unload "$dst" 2>/dev/null || true
    launchctl load -w "$dst"
    echo "   loaded $label"
  fi
}

echo "==> installing launchd jobs"
install_job com.sweepstake.serve
install_job com.sweepstake.update
if [ "$WANT_SOFA" = 1 ]; then
  install_job com.sweepstake.watch
else
  echo "   skipping com.sweepstake.watch (re-run with --sofascore to enable it)"
fi

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '<mac-mini-ip>')"
echo
echo "Done. The sweepstake is live at:"
echo "   http://localhost:8123          (on the Mac mini itself)"
echo "   http://$IP:8123   (phones/laptops on the same wifi)"
[ "$LOAD" = 1 ] && echo "Check it's running:  launchctl list | grep sweepstake"
echo "Logs:  $REPO/logs/"
