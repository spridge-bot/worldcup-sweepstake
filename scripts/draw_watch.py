#!/usr/bin/env python3
"""Wait for the manual draw to finish, then bring the sweepstake live and keep
it updating in the background.

Phase 1 — WAIT: poll var/draw_state.json. Collect the 'lock' events broadcast
since the last 'reset'. The moment every player in data/players.json holds 3
teams, write that draw into data/players.json. (If someone instead drops a
fully-drawn players.json in by hand, that's detected too.)

Phase 2 — LIVE: run update_scores.py on a loop so results, the leaderboard and
every other feature stay current, and start the sofascore live watcher while
matches are in play (mirrors scripts/mini_update.sh).

Stdlib only. Logs to logs/draw_watch.log. Stop with: pkill -f draw_watch.py
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "var" / "draw_state.json"
PLAYERS = ROOT / "data" / "players.json"
DATA = ROOT / "docs" / "data.json"
PY = sys.executable or "/usr/bin/python3"
TEAMS_PER_PLAYER = 4

# the public draw page (GitHub Pages) broadcasts spins over this ntfy relay
NTFY_TOPIC = "wc26-sweepstake-draw-spridge-k7q4x9"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}/json?poll=1&since=12h"


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def player_names():
    return [p["name"] for p in json.loads(PLAYERS.read_text())["players"]]


def _assignments(events):
    """{player: [teams]} from lock events after the latest draw-start boundary.

    A new draw begins at a 'reset' or a round-1 'spin', so reruns supersede
    earlier attempts cleanly.
    """
    boundary = -1
    for i, e in enumerate(events):
        if e.get("type") == "reset" or (e.get("type") == "spin" and e.get("round") == 1):
            boundary = i
    out = {}
    for e in events[boundary + 1:]:
        if e.get("type") == "lock" and e.get("player") and e.get("team"):
            picks = out.setdefault(e["player"], [])
            if e["team"] not in picks:
                picks.append(e["team"])
    return out


def assignments_from_state():
    """Local draw — spins captured by scripts/serve.py into var/draw_state.json."""
    try:
        return _assignments(json.loads(STATE.read_text()).get("events", []))
    except Exception:
        return {}


def assignments_from_ntfy():
    """Public draw — spins broadcast over the ntfy relay from GitHub Pages."""
    try:
        req = urllib.request.Request(NTFY_URL, headers={"User-Agent": "draw-watch"})
        raw = urllib.request.urlopen(req, timeout=15).read().decode()
    except Exception:
        return {}
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("event") != "message":
                continue
            ev = json.loads(msg.get("message", "{}"))
        except Exception:
            continue
        if isinstance(ev, dict) and ev.get("type"):
            events.append(ev)
    return _assignments(events)


def manual_draw():
    """Return assignments if players.json was already filled in by hand, else None."""
    placed = {p["name"]: p.get("teams", []) for p in json.loads(PLAYERS.read_text())["players"]}
    if placed and all(len(v) == TEAMS_PER_PLAYER for v in placed.values()):
        return placed
    return None


def complete_draw():
    """Return the finished assignments dict, or None if the draw isn't done yet.

    Checks, in order: a hand-placed players.json, the local server's draw state,
    then the public ntfy relay — so it captures the draw wherever it's run.
    """
    manual = manual_draw()
    if manual is not None:
        return manual
    names = player_names()
    for source in (assignments_from_state, assignments_from_ntfy):
        a = source()
        if names and all(len(a.get(n, [])) == TEAMS_PER_PLAYER for n in names):
            return a
    return None


def apply_draw(a):
    doc = json.loads(PLAYERS.read_text())
    for p in doc["players"]:
        p["teams"] = a.get(p["name"], [])
    PLAYERS.write_text(json.dumps(doc, indent=2) + "\n")
    picks = sum(len(v) for v in a.values())
    log(f"Draw captured: {picks} picks across {len(a)} players -> data/players.json")


def run_update():
    r = subprocess.run([PY, "scripts/update_scores.py"], cwd=ROOT,
                       capture_output=True, text=True)
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    log("update: " + (tail[-1] if tail else "(no output)"))


def matches_live():
    try:
        return bool(json.loads(DATA.read_text()).get("live"))
    except Exception:
        return False


def ensure_live_watcher():
    running = subprocess.run(["pgrep", "-f", "sofascore_live.py --watch"],
                             capture_output=True).returncode == 0
    if not running:
        (ROOT / "logs").mkdir(exist_ok=True)
        f = open(ROOT / "logs" / "watch.log", "a")
        subprocess.Popen([PY, "scripts/sofascore_live.py", "--watch", "25"],
                         cwd=ROOT, stdout=f, stderr=f)
        log("started sofascore live watcher")


def main():
    log("draw watcher started — waiting for the draw to complete...")
    while True:
        done = complete_draw()
        if done is not None:
            if manual_draw() is None:        # came from the wheel, not hand-placed
                apply_draw(done)
            else:
                log("players.json already holds a complete draw — going live")
            break
        time.sleep(3)

    run_update()
    log("sweepstake is LIVE — continuous update mode (results, leaderboard, all features)")
    while True:
        run_update()
        if matches_live():
            ensure_live_watcher()
            time.sleep(60)
        else:
            time.sleep(180)


if __name__ == "__main__":
    main()
