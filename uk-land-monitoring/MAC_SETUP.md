# Set up on your Mac mini — copy, paste, approve

Everything runs **on the Mac mini in Terminal**. One installer does the whole job and
pauses for the few things only you can approve. Total time ≈ 10 minutes (mostly the
dependency download).

## What you'll be asked to approve
1. **Xcode Command Line Tools** — the first time you run `git`, macOS pops up an
   "Install" button. Click it. (Skip if you use the ZIP option below.)
2. **Your Mac password** — only if Homebrew/Python need installing.
3. **Your OS API key** — the installer asks you to paste it (free, link provided).
4. **Tailscale** — if installed, it's published automatically; otherwise one command.

Nothing is destructive, and the installer is safe to re-run.

---

## Step 0 — get the code onto the Mac

**Option A — no Terminal login (easiest):**
1. On the Mac, open this repo on GitHub in Safari, switch to the branch
   **`claude/uk-maps-satellite-imagery-9cyw1l`**, click **Code ▸ Download ZIP**.
2. Double-click the ZIP in Downloads to unzip it.
3. In Terminal:
   ```bash
   cd ~/Downloads/worldcup-sweepstake-*/uk-land-monitoring
   ```

**Option B — git clone (if you're signed into GitHub on the Mac):**
```bash
git clone -b claude/uk-maps-satellite-imagery-9cyw1l \
  https://github.com/spridge-bot/worldcup-sweepstake.git
cd worldcup-sweepstake/uk-land-monitoring
```

## Step 1 — run the installer
```bash
bash install_mac.sh
```
That's it. It installs Python + dependencies, asks for your OS key, builds the first
dataset, starts the dashboard, schedules the weekly refresh, and (if Tailscale is
present) publishes it. When it finishes it prints your dashboard URL.

---

## After it finishes
- **Local:** open <http://127.0.0.1:8000> on the Mac.
- **From your phone/laptop:** the printed `https://<machine>.<tailnet>.ts.net` URL
  (works anywhere your Tailscale is signed in). If Tailscale wasn't installed, install
  the app, sign in, then run `tailscale serve --bg 8000`.
- **Weekly refresh:** runs automatically every Sunday at 03:00 and updates the
  dashboard with no restart. Check it ran with `tail uk-land-monitoring/outputs/refresh.log`.

## Changing the area you monitor
Edit `config/aoi.example.geojson` (a polygon in lon/lat), then rebuild:
```bash
cd ~/.../uk-land-monitoring
make pipeline AOI=config/aoi.example.geojson START=2025-06-01 END=2026-06-20
```
The running dashboard picks up the new data automatically. To draw an AOI visually,
use <https://geojson.io>, paste/replace the polygon, and save over the file.

## Want a file you can just open (no server, no Mac)?
```bash
make static     # -> outputs/dashboard_demo.html
```
That bakes the data + chips into one self-contained HTML you can email/AirDrop and open
in any browser (it still needs internet for the map tiles). Run it after `make pipeline`
to share a snapshot of your real data.

## If something fails
- The dashboard always still runs (on demo or the previous week's data), so a failed
  refresh never leaves you with a blank page.
- Most issues are the OS key or the date window — see `SETUP.md` §3 (Troubleshooting).
- Re-run `bash install_mac.sh` any time; it's idempotent.
