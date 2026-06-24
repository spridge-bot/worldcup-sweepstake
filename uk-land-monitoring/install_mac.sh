#!/usr/bin/env bash
# Land Monitor — one-shot macOS installer for a Mac mini.
#
# Run it from inside the project dir:
#     cd worldcup-sweepstake/uk-land-monitoring
#     bash install_mac.sh
#
# It is interactive and idempotent: safe to re-run. It will pause for the few
# approvals only you can give (Homebrew password, your OS API key, Tailscale).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
say()  { printf "\n\033[1;34m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!! \033[0m %s\n" "$*"; }

# --- 1. Python 3 --------------------------------------------------------- #
say "Checking for Python 3…"
if ! command -v python3 >/dev/null 2>&1; then
  warn "Python 3 not found — installing via Homebrew (you'll be asked to approve)."
  if ! command -v brew >/dev/null 2>&1; then
    say "Installing Homebrew (needs your Mac password)…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
  fi
  brew install python
fi
python3 --version

# --- 2. venv + dependencies --------------------------------------------- #
say "Creating the virtual environment and installing dependencies (a few minutes)…"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
pip install -r requirements.txt
say "Dependencies installed."

# --- 3. OS Data Hub API key --------------------------------------------- #
[ -f .env ] || cp .env.example .env 2>/dev/null || true
if ! grep -Eq '^OS_API_KEY=.+' .env 2>/dev/null; then
  echo
  say "You need a FREE Ordnance Survey Data Hub API key:"
  echo "    1) Sign in / sign up at  https://osdatahub.os.uk/"
  echo "    2) Create an API project; add 'OS NGD API – Features' and 'OS Maps API'"
  echo "    3) Copy the Project API Key"
  echo
  printf "\033[1;33m??\033[0m Paste your OS_API_KEY (or press Enter to skip and use demo data): "
  read -r OSKEY
  python3 - "$OSKEY" <<'PY'
import sys, pathlib
key = sys.argv[1].strip()
p = pathlib.Path(".env")
lines = p.read_text().splitlines() if p.exists() else []
out, done = [], False
for ln in lines:
    if ln.startswith("OS_API_KEY="):
        out.append(f"OS_API_KEY={key}"); done = True
    else:
        out.append(ln)
if not done:
    out.append(f"OS_API_KEY={key}")
p.write_text("\n".join(out) + "\n")
PY
  grep -Eq '^OS_API_KEY=.+' .env && say "Saved your key to .env" || warn "No key set — using bundled demo data."
fi

# --- 4. First data build (only if a key is present) ---------------------- #
export PYTHONPATH="$HERE/src"
if grep -Eq '^OS_API_KEY=.+' .env 2>/dev/null; then
  END="$(date +%F)"
  if date -v-12m +%F >/dev/null 2>&1; then START="$(date -v-12m +%F)"; else START="$(date -d '12 months ago' +%F)"; fi
  say "Building the first dataset for $START..$END (OS buildings + free satellite)…"
  if ! python -m landmon.cli pipeline --aoi config/aoi.example.geojson \
        --start "$START" --end "$END" --sensor s1 --chips --chip-mode rgb; then
    warn "Pipeline hit an error (see above). The dashboard still runs on demo/previous"
    warn "data — fix the issue (see SETUP.md) and re-run:  make pipeline"
  fi
else
  python3 scripts/make_demo_timeseries.py >/dev/null 2>&1 || true
fi

# --- 5. Background services: dashboard + weekly refresh ------------------ #
say "Installing background services (always-on dashboard + weekly refresh)…"
LA="$HOME/Library/LaunchAgents"; mkdir -p "$LA"
for f in com.landmon.viewer com.landmon.refresh; do
  sed "s#__PROJECT_DIR__#$HERE#g" "deploy/$f.plist" > "$LA/$f.plist"
  launchctl unload "$LA/$f.plist" 2>/dev/null || true
  launchctl load   "$LA/$f.plist"
done
say "Dashboard runs now and on every reboot. Refresh runs weekly (Sundays 03:00)."

# --- 6. Tailscale -------------------------------------------------------- #
echo
if command -v tailscale >/dev/null 2>&1; then
  say "Publishing the dashboard on your tailnet (private HTTPS)…"
  tailscale serve --bg 8000 2>/dev/null || warn "Run it yourself once logged in:  tailscale serve --bg 8000"
  URL="$(tailscale status --json 2>/dev/null | python3 -c 'import sys,json;print("https://"+json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
  [ -n "${URL:-}" ] && say "Reach it from any of your devices at:  $URL"
else
  warn "Tailscale not found. Install the Tailscale app and sign in, then run:"
  echo  "      tailscale serve --bg 8000"
fi

say "All done. Local dashboard:  http://127.0.0.1:8000"
say "Re-run this script any time; manual refresh:  bash scripts/refresh.sh"
