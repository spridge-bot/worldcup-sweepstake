# Deploy: always-on dashboard + weekly refresh

Two pieces: a **viewer** that stays up, and a **refresh** that re-runs the pipeline
weekly. The viewer reads `outputs/activity.geojson` on every request, so a refresh
updates the live dashboard with **no restart**. `scripts/refresh.sh` stages results in
a temp dir and swaps them in atomically — a failed run keeps the previous data.

First, in every file in this folder replace `__PROJECT_DIR__` with the absolute path to
`uk-land-monitoring`. Quick way:

```bash
cd uk-land-monitoring
P="$(pwd)"
for f in deploy/*; do sed -i.bak "s#__PROJECT_DIR__#$P#g" "$f" && rm -f "$f.bak"; done
```

Make sure setup is done first (see ../SETUP.md): `.venv` created, deps installed,
`OS_API_KEY` in `.env`. Test once by hand: `bash scripts/refresh.sh` then `tail outputs/refresh.log`.

---

## macOS (launchd) — likely your machine

```bash
cp deploy/com.landmon.viewer.plist  ~/Library/LaunchAgents/
cp deploy/com.landmon.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.landmon.viewer.plist   # starts the server, KeepAlive
launchctl load ~/Library/LaunchAgents/com.landmon.refresh.plist  # weekly, Sundays 03:00
# check:  launchctl list | grep landmon
# run the refresh now to test:  launchctl start com.landmon.refresh
```

## Linux (systemd user units)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/landmon-*.service deploy/landmon-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now landmon-viewer.service     # dashboard
systemctl --user enable --now landmon-refresh.timer      # weekly
loginctl enable-linger "$USER"                           # keep running while logged out
# run the refresh now to test:  systemctl --user start landmon-refresh.service
```

## Anywhere (cron)
If you'd rather not use a service manager, just schedule the refresh and run the
viewer however you like:
```bash
crontab -e        # paste the line from deploy/crontab.example
```

---

## Reach it over Tailscale
Once the viewer is up on `127.0.0.1:8000`:
```bash
tailscale serve --bg 8000      # -> https://<machine>.<tailnet>.ts.net  (tailnet-only HTTPS)
```
Keep the viewer bound to `127.0.0.1` and let `tailscale serve` expose it — it has no auth
of its own. See the main README "Viewing over Tailscale".

## Tuning the refresh
`refresh.sh` honours env vars (set them in the cron line / unit if you want):
`AOI`, `SENSOR` (s1|s2), `CHIP_MODE` (rgb|ndvi|sar), `MONTHS` (rolling window, default 12).
