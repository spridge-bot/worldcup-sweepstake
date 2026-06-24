# Running the sweepstake on a Mac mini

These launchd jobs make the Mac mini self-run the sweepstake across reboots:
serve the leaderboard on the LAN, keep scores fresh, and (optionally) drive the
live Sofascore layer.

## One-shot setup

```sh
git clone https://github.com/spridge-bot/worldcup-sweepstake.git ~/worldcup-sweepstake
cd ~/worldcup-sweepstake
scripts/bootstrap_macmini.sh              # scores-only (core, no pip installs)
# or, for the full live experience:
scripts/bootstrap_macmini.sh --sofascore --pitch
```

The bootstrap refreshes scores once, optionally builds the pitch venv / installs
`datafc`, then installs and loads the jobs below. It rewrites the
`/Users/ianspridgeon/...` paths baked into the plists to wherever you cloned the
repo, so it works for any user/location.

## The jobs

| Job | What it does | Cadence | Needs |
|---|---|---|---|
| `com.sweepstake.serve` | Serves `docs/` + live-draw API on **:8123** | always on (KeepAlive) | nothing |
| `com.sweepstake.update` | `update_scores.py` — ESPN scores + scoring | every 5 min | nothing |
| `com.sweepstake.watch` | `sofascore_live.py --watch` — incidents, line-ups, momentum, pitch art | always on (KeepAlive) | `pip3 install datafc` (+ `.venv-pitch` for PNGs) |

Open `http://<mac-mini-ip>:8123` from any phone/laptop on the same wifi.

## Managing the jobs

```sh
launchctl list | grep sweepstake          # see what's loaded
launchctl unload ~/Library/LaunchAgents/com.sweepstake.serve.plist   # stop one
launchctl load -w ~/Library/LaunchAgents/com.sweepstake.serve.plist  # start one
tail -f ~/worldcup-sweepstake/logs/*.log  # watch the logs
```

## Notes

- **Scores-only is enough** for the leaderboard. The `watch` job only adds the
  rich live detail (timelines, momentum, pitch maps) and is skipped unless you
  pass `--sofascore`.
- The `watch` loop is persistent — when no match is live it idle-polls every
  ~30s instead of exiting, so `KeepAlive` does not cause a restart storm.
- This is the **standalone** Mac mini setup. The separate `auto_sync.sh` /
  `live_push.sh` scripts are for the publisher topology (a worktree pushing the
  `live-data` branch, an iMac rsyncing to the mini) and are not needed here.
