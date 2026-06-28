#!/usr/bin/env bash
# Wide-area SCAN: map every candidate storage farm in a big radius, FAST (no
# satellite). Ranks by an opportunity score (size + storage-type + isolation).
# Usage:  bash scripts/scan.sh "OX27 7JE" [radius_km, default 32 = ~20 miles]
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
POSTCODE="${1:-OX27 7JE}"
RADIUS="${2:-32}"

[ -d .venv ] && source .venv/bin/activate
export PYTHONPATH="$HERE/src"

echo "==> 1/3 Mapping candidate storage farms within ${RADIUS} km of '$POSTCODE' (no satellite, fast)…"
python -m landmon.cli pipeline --postcode "$POSTCODE" --radius-km "$RADIUS" \
    --start 2025-01-01 --end 2025-12-31 --no-activity --max 20000 || {
  echo "!! scan failed — see error above"; exit 1; }

echo "==> 2/3 Grouping into farm holdings (fast: no land lookup)…"
python -m landmon.cli farms --no-land || echo "   (farms skipped)"

echo "==> 3/3 Restarting the dashboard…"
echo "    (Names + ownership links are added later when you deep-analyse a shortlist.)"
launchctl unload "$HOME/Library/LaunchAgents/com.landmon.viewer.plist" 2>/dev/null || true
launchctl load   "$HOME/Library/LaunchAgents/com.landmon.viewer.plist" 2>/dev/null || true

echo ""
echo "==> Wide scan done. Open http://127.0.0.1:8000 and press Cmd+Shift+R."
echo "    Sites are ranked 'Strong / Moderate / Weak' candidate (by size + type +"
echo "    isolation). To measure which are actually QUIET/available, deep-analyse a"
echo "    shortlist:  bash scripts/area.sh \"<a postcode in that cluster>\" 2"
