#!/usr/bin/env python3
"""Sofascore live layer: minute-by-minute incidents, confirmed line-ups,
live match stats and average player positions, rendered onto an aerial
pitch with mplsoccer.

Uses ScraperFC's bundled botasaurus browser. Sofascore's API challenges
direct requests, so we load the real match pages and harvest the JSON
responses the page itself fetches (incidents / lineups / statistics /
average-positions).

Modes:
    sofascore_live.py             one pass over matches near now
    sofascore_live.py --watch 45  stay running while matches are live:
                                  every ~45s re-harvest positions/stats/
                                  incidents, patch the live score in
                                  data.json, redraw the pitch and mirror
                                  docs/ to the Mac mini. Exits when no
                                  match is live.

Outputs:
    docs/sofascore.json        {espn_match_id: {incidents, lineups, stats,
                                positions, pitch, sofa_id, updated}}
    docs/img/pitch_<id>.png    aerial average-position pitch view (mplsoccer)

Fails soft: any missing dependency or blocked request leaves the existing
files untouched.
"""
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
IMG = DOCS / "img"
WINDOW_BACK_H = 8     # cover matches that finished earlier today
WINDOW_FWD_H = 12     # and ones kicking off soon (line-ups confirm ~1h before)
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"

try:
    from botasaurus.browser import browser, Driver
except ImportError:
    sys.exit("ScraperFC/botasaurus not installed — pip3 install ScraperFC mplsoccer")


def normalize(name):
    name = unicodedata.normalize("NFKD", str(name))
    return "".join(c for c in name.lower() if c.isalpha())


def load_targets():
    """Matches near now from our own data.json: {frozenset(codes): espn_id}."""
    data = json.loads((DOCS / "data.json").read_text())
    name_to_code = {}
    variants = {}
    for code, t in data["teams"].items():
        variants[code] = {normalize(t["name"]), normalize(code)}
        name_to_code[normalize(t["name"])] = code
    # teams.json aliases give better slug matching (e.g. cote-divoire)
    for t in json.loads((ROOT / "data/teams.json").read_text())["teams"]:
        variants[t["code"]].update(normalize(a) for a in t.get("aliases", []))

    now = datetime.now(timezone.utc)
    targets = {}
    rows = (list(data.get("live") or []) + list(data.get("results") or [])
            + list(data.get("upcoming") or []))
    for r in rows:
        utc = r.get("utc")
        if not utc or not r.get("id"):
            continue
        when = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        if not (now - timedelta(hours=WINDOW_BACK_H) <= when <= now + timedelta(hours=WINDOW_FWD_H)):
            continue
        hc = r["home"].get("code") or name_to_code.get(normalize(r["home"]["name"]))
        ac = r["away"].get("code") or name_to_code.get(normalize(r["away"]["name"]))
        if hc and ac:
            targets[frozenset((hc, ac))] = r["id"]
    live_ids = {m["id"] for m in data.get("live") or []}
    return targets, variants, data["teams"], live_ids


def slug_to_codes(slug, variants):
    """'mexico-south-africa' -> ('MEX', 'RSA') using team name variants."""
    s = normalize(slug.replace("-", ""))
    for ca, va in variants.items():
        for a in sorted(va, key=len, reverse=True):
            if a and s.startswith(a):
                rest = s[len(a):]
                for cb, vb in variants.items():
                    if cb != ca and rest in vb:
                        return ca, cb
    return None, None


@browser(headless=True, output=None, create_error_logs=False, reuse_driver=True,
         block_images_and_css=True)
def discover_links(driver: Driver, data):
    links = set()
    for url in data["urls"]:
        try:
            driver.get(url)
            driver.sleep(4)
            found = driver.run_js(
                "return JSON.stringify([...document.querySelectorAll("
                "'a[href*=\"/football/match/\"]')].map(a => a.href))")
            links.update(json.loads(found))
        except Exception as e:
            print(f"  discover {url} failed ({e})")
    return sorted(links)


@browser(headless=True, output=None, create_error_logs=False, reuse_driver=True,
         block_images_and_css=True)
def capture_match(driver: Driver, job):
    """Open a match page and harvest the API JSON the page fetches."""
    import base64
    url = job["url"] if isinstance(job, dict) else job
    quick = bool(isinstance(job, dict) and job.get("quick"))
    hits = {}

    def handler(request_id, response, event):
        if "/api/v1/event/" in response.url:
            hits[request_id] = response.url

    driver.after_response_received(handler)
    driver.get(url)
    driver.sleep(3 if quick else 7)
    for frac in (0.4, 0.8):    # average-positions loads when scrolled into view
        driver.run_js(f"window.scrollTo(0, document.body.scrollHeight*{frac})")
        driver.sleep(1.5 if quick else 2)
    out = {}
    for rid, u in list(hits.items()):
        key = u.split("/api/v1/")[1].split("?")[0]
        short = next((k for k in ("incidents", "lineups", "average-positions", "statistics")
                      if key.endswith(k)), None)
        if not short or short in out:
            continue
        try:
            r = driver.collect_response(rid)
            c = r.content
            if c and r.is_base_64:
                c = base64.b64decode(c).decode("utf-8", "replace")
            if c:
                out[short] = json.loads(c)
        except Exception:
            pass
    return out


def parse_incidents(raw):
    out = []
    for i in reversed(raw.get("incidents", [])):     # chronological order
        ent = {
            "type": i.get("incidentType"),
            "class": i.get("incidentClass"),
            "minute": i.get("time") if (i.get("time") or 0) >= 0 else None,
            "addedTime": i.get("addedTime") if i.get("addedTime") not in (None, 999) else None,
            "team": ("home" if i.get("isHome") else "away") if i.get("isHome") is not None else None,
            "player": (i.get("player") or {}).get("shortName"),
            "assist": (i.get("assist1") or {}).get("shortName"),
            "in": (i.get("playerIn") or {}).get("shortName"),
            "out": (i.get("playerOut") or {}).get("shortName"),
            "text": i.get("text"),
            "homeScore": i.get("homeScore"),
            "awayScore": i.get("awayScore"),
            "length": i.get("length"),
        }
        out.append({k: v for k, v in ent.items() if v is not None})
    return out


def parse_lineups(raw):
    def side(s):
        players = s.get("players") or []
        def pl(p):
            return {"name": (p.get("player") or {}).get("shortName")
                    or (p.get("player") or {}).get("name", "?"),
                    "shirt": p.get("jerseyNumber"),
                    "position": p.get("position")}
        return {
            "formation": s.get("formation"),
            "lineup": [pl(p) for p in players if not p.get("substitute")],
            "bench": [pl(p) for p in players if p.get("substitute")],
        }
    return {"confirmed": bool(raw.get("confirmed")),
            "home": side(raw.get("home") or {}),
            "away": side(raw.get("away") or {})}


SOFA_STAT_MAP = {
    "Ball possession": "ball_possession",
    "Total shots": "shots",
    "Shots on target": "shots_on_goal",
    "Corner kicks": "corner_kicks",
    "Fouls": "fouls",
    "Passes": "passes",
    "Long balls": "long_balls",
    "Crosses": "crosses",
    "Offsides": "offsides",
    "Yellow cards": "yellow_cards",
    "Red cards": "red_cards",
    "Goalkeeper saves": "saves",
}


def parse_statistics(raw):
    """Live match stats -> same keys the match centre uses for its bars."""
    out = {"home": {}, "away": {}}
    for period in raw.get("statistics") or []:
        if period.get("period") != "ALL":
            continue
        for g in period.get("groups") or []:
            for it in g.get("statisticsItems") or []:
                key = SOFA_STAT_MAP.get(it.get("name"))
                if not key:
                    continue
                for side in ("home", "away"):
                    m = re.search(r"\d+(?:\.\d+)?", str(it.get(side, "")))
                    if m:
                        v = float(m.group())
                        out[side].setdefault(key, int(v) if v == int(v) else v)
    return out if (out["home"] or out["away"]) else None


def parse_positions(raw):
    out = {}
    for side in ("home", "away"):
        out[side] = [{
            "name": (p.get("player") or {}).get("shortName")
                    or (p.get("player") or {}).get("name", "?"),
            "shirt": (p.get("player") or {}).get("jerseyNumber"),
            "x": round(p.get("averageX", 0), 1),
            "y": round(p.get("averageY", 0), 1),
        } for p in raw.get(side) or [] if p.get("averageX") is not None]
    return out


def draw_pitch(path, home, away, positions):
    """Render via render_pitch.py in the mplsoccer venv (needs Python >= 3.10)."""
    import os
    import tempfile

    candidates = [os.environ.get("PITCH_PYTHON"),
                  str(ROOT / ".venv-pitch/bin/python"),
                  sys.executable]
    py = next((c for c in candidates if c and Path(c).exists()), None)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(positions, f)
        tmp = f.name
    try:
        subprocess.run([py, str(ROOT / "scripts/render_pitch.py"), tmp, str(path),
                        home, away], check=True, capture_output=True, timeout=120)
    finally:
        os.unlink(tmp)


def harvest(link, espn_id, codes, teams, out, quick=False):
    """Capture one match page into the sofascore.json dict. Returns captured keys."""
    ca, cb = codes
    payloads = capture_match({"url": link, "quick": quick})
    ent = out.get(str(espn_id), {})
    sofa_id = re.search(r"#id:(\d+)", link)
    ent.update({"sofa_id": sofa_id.group(1) if sofa_id else None,
                "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    if payloads.get("incidents"):
        ent["incidents"] = parse_incidents(payloads["incidents"])
    if payloads.get("lineups"):
        ent["lineups"] = parse_lineups(payloads["lineups"])
    if payloads.get("statistics"):
        stats = parse_statistics(payloads["statistics"])
        if stats:
            ent["stats"] = stats
    if payloads.get("average-positions"):
        pos = parse_positions(payloads["average-positions"])
        if pos.get("home") or pos.get("away"):
            ent["positions"] = pos
            img = IMG / f"pitch_{espn_id}.png"
            try:
                draw_pitch(img, teams.get(ca, {}).get("name", ca),
                           teams.get(cb, {}).get("name", cb), pos)
                ent["pitch"] = f"img/pitch_{espn_id}.png"
            except Exception as e:
                print(f"  pitch render failed ({e})")
    out[str(espn_id)] = ent
    return [k for k in ("incidents", "lineups", "stats", "positions", "pitch") if ent.get(k)]


def find_matches(targets, variants):
    """Map Sofascore match links to our ESPN ids. {espn_id: (link, (codeA, codeB))}"""
    today = datetime.now(timezone.utc)
    urls = ["https://www.sofascore.com/football/livescore",
            f"https://www.sofascore.com/football/{today:%Y-%m-%d}"]
    found = {}
    for link in discover_links({"urls": urls}):
        m = re.search(r"/football/match/([a-z0-9-]+)/[A-Za-z]+#id:(\d+)", link or "")
        if not m:
            continue
        ca, cb = slug_to_codes(m.group(1), variants)
        espn_id = targets.get(frozenset((ca, cb))) if ca and cb else None
        if espn_id and espn_id not in found:
            found[espn_id] = (link, (ca, cb))
    return found


def espn_quick_scores():
    """One cheap ESPN call: patch score/clock for the live matches in data.json."""
    now = datetime.now(timezone.utc)
    rng = f"{now - timedelta(days=1):%Y%m%d}-{now + timedelta(days=1):%Y%m%d}"
    try:
        req = urllib.request.Request(f"{ESPN_SCOREBOARD}?dates={rng}",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            events = json.loads(resp.read()).get("events", [])
    except Exception as e:
        print(f"  quick score fetch failed ({e})")
        return
    by_id = {}
    for e in events:
        c = (e.get("competitions") or [{}])[0]
        comps = c.get("competitors") or []
        home = next((t for t in comps if t.get("homeAway") == "home"), None)
        away = next((t for t in comps if t.get("homeAway") == "away"), None)
        state = (e.get("status") or {}).get("type") or {}
        if home and away:
            by_id[int(e["id"])] = {
                "hg": int(home.get("score") or 0), "ag": int(away.get("score") or 0),
                "clock": (e.get("status") or {}).get("displayClock"),
                "detail": state.get("shortDetail"),
                "live": state.get("state") == "in",
            }
    path = DOCS / "data.json"
    data = json.loads(path.read_text())
    changed = False
    still_live = []
    for m in data.get("live") or []:
        ev = by_id.get(m.get("id"))
        if not ev:
            still_live.append(m)
            continue
        if (m["home"]["goals"], m["away"]["goals"], m.get("clock")) != (ev["hg"], ev["ag"], ev["clock"]):
            m["home"]["goals"], m["away"]["goals"] = ev["hg"], ev["ag"]
            m["clock"], m["status_detail"] = ev["clock"], ev["detail"]
            changed = True
        if ev["live"]:
            still_live.append(m)
        else:
            changed = True      # gone final; full updater will file the result
    if changed:
        data["live"] = still_live
        data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        print("  patched live scores in data.json")


def mirror_to_mini():
    subprocess.run(
        ["rsync", "-a", "--exclude", ".DS_Store",
         str(DOCS) + "/", "macmini:worldcup-sweepstake/docs/"],
        capture_output=True, timeout=60)


def write_out(out):
    (DOCS / "sofascore.json").write_text(json.dumps(out, ensure_ascii=False) + "\n")


def main():
    targets, variants, teams, _ = load_targets()
    if not targets:
        print("No matches within the live window; nothing to do.")
        return
    print(f"Looking for {len(targets)} match(es) on Sofascore...")
    found = find_matches(targets, variants)
    sofa_path = DOCS / "sofascore.json"
    out = json.loads(sofa_path.read_text()) if sofa_path.exists() else {}
    IMG.mkdir(exist_ok=True)
    for espn_id, (link, codes) in found.items():
        print(f"  {link.split('/match/')[1].split('/')[0]} -> match {espn_id}")
        got = harvest(link, espn_id, codes, teams, out)
        print(f"    captured: {', '.join(got) or 'nothing yet'}")
    write_out(out)
    print(f"Wrote docs/sofascore.json ({len(out)} matches)")


def watch(interval):
    """Stay running while matches are live; refresh every `interval` seconds."""
    print(f"Watch mode: refreshing live matches every ~{interval}s")
    sofa_path = DOCS / "sofascore.json"
    out = json.loads(sofa_path.read_text()) if sofa_path.exists() else {}
    IMG.mkdir(exist_ok=True)
    found = {}
    idle_passes = 0
    while True:
        cycle_start = time.time()
        espn_quick_scores()
        targets, variants, teams, live_ids = load_targets()
        if not live_ids:
            idle_passes += 1
            if idle_passes >= 3:        # give a just-finished match time to settle
                print("No live matches; watcher exiting.")
                break
        else:
            idle_passes = 0
            if any(mid not in found for mid in live_ids):
                found = find_matches(targets, variants)
            for mid in live_ids:
                if mid not in found:
                    continue
                link, codes = found[mid]
                got = harvest(link, mid, codes, teams, out, quick=True)
                print(f"  [{datetime.now():%H:%M:%S}] match {mid}: {', '.join(got)}")
            write_out(out)
            mirror_to_mini()
        time.sleep(max(5, interval - (time.time() - cycle_start)))


if __name__ == "__main__":
    if "--watch" in sys.argv:
        idx = sys.argv.index("--watch")
        secs = int(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 and sys.argv[idx + 1].isdigit() else 45
        watch(secs)
    else:
        main()
