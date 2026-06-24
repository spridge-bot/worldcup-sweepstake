#!/usr/bin/env bash
# Weekly refresh: re-run the pipeline over a rolling 12-month window and swap the
# results into outputs/ atomically. A failed/empty run keeps the previous data so
# the live dashboard never breaks. Safe to run from cron, systemd, or launchd.
#
# Env overrides: AOI, SENSOR (s1|s2), CHIP_MODE (rgb|ndvi|sar), MONTHS (default 12).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/outputs"
LOG="$ROOT/outputs/refresh.log"
ts() { date '+%Y-%m-%dT%H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

[ -d "$ROOT/.venv" ] && . "$ROOT/.venv/bin/activate"
export PYTHONPATH="$ROOT/src"

MONTHS="${MONTHS:-12}"
END="$(date +%F)"
if date -d "$MONTHS months ago" +%F >/dev/null 2>&1; then
  START="$(date -d "$MONTHS months ago" +%F)"      # GNU/Linux
else
  START="$(date -v-"${MONTHS}"m +%F)"              # BSD/macOS
fi
AOI="${AOI:-config/aoi.example.geojson}"
SENSOR="${SENSOR:-s1}"
CHIP_MODE="${CHIP_MODE:-rgb}"

log "refresh START aoi=$AOI window=$START..$END sensor=$SENSOR chips=$CHIP_MODE"
STAGE="$ROOT/outputs/.staging"
rm -rf "$STAGE"; mkdir -p "$STAGE"

if python -m landmon.cli pipeline --aoi "$AOI" --start "$START" --end "$END" \
      --sensor "$SENSOR" --chips --chip-mode "$CHIP_MODE" --outdir "$STAGE" >>"$LOG" 2>&1; then
  if python -c "import json,sys; d=json.load(open('$STAGE/activity.geojson')); sys.exit(0 if d.get('features') else 1)" 2>/dev/null; then
    mv -f "$STAGE/storage.geojson"  "$ROOT/outputs/storage.geojson"  2>/dev/null || true
    mv -f "$STAGE/activity.geojson" "$ROOT/outputs/activity.geojson"
    if [ -d "$STAGE/chips" ]; then
      rm -rf "$ROOT/outputs/chips"; mv -f "$STAGE/chips" "$ROOT/outputs/chips"
    fi
    n=$(python -c "import json;print(len(json.load(open('$ROOT/outputs/activity.geojson'))['features']))")
    log "refresh OK -> outputs/activity.geojson ($n buildings). Dashboard updates live."
  else
    log "ERROR: pipeline produced no features — keeping previous outputs."
  fi
else
  log "ERROR: pipeline failed (network/key/AOI?) — keeping previous outputs. See log above."
fi
rm -rf "$STAGE"
