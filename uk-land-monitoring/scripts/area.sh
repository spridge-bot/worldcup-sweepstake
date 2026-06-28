#!/usr/bin/env bash
# One command to point the dashboard at a postcode and rebuild everything.
# Usage:  bash scripts/area.sh "OX27 7JE" [radius_km] [start] [end]
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
POSTCODE="${1:-OX27 7JE}"
RADIUS="${2:-2}"
START="${3:-2025-06-01}"
END="${4:-$(date +%F)}"

[ -d .venv ] && source .venv/bin/activate
export PYTHONPATH="$HERE/src"

echo "==> 1/4 Building OS buildings + satellite activity for '$POSTCODE' (~10-15 min)…"
python -m landmon.cli pipeline --postcode "$POSTCODE" --radius-km "$RADIUS" \
    --start "$START" --end "$END" --chips --chip-mode rgb || {
  echo "!! pipeline failed — see the error above"; exit 1; }

echo "==> 2/4 Adding location/farm names + ownership links…"
python -m landmon.cli enrich || echo "   (enrich skipped: $?)"

echo "==> 3/4 Grouping into farm holdings + land…"
python -m landmon.cli farms || echo "   (farms skipped: $?)"

echo "==> 4/4 Restarting the dashboard…"
launchctl unload "$HOME/Library/LaunchAgents/com.landmon.viewer.plist" 2>/dev/null || true
launchctl load   "$HOME/Library/LaunchAgents/com.landmon.viewer.plist" 2>/dev/null || true

echo ""
echo "==> Done. Open http://127.0.0.1:8000 and press Cmd+Shift+R."
echo "    (If reaching from your phone: your tailnet URL.)"
