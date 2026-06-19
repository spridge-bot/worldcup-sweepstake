#!/usr/bin/env python3
"""Sofascore live layer: minute-by-minute incidents, confirmed line-ups,
live match stats, attack momentum, shotmaps (with xG) and average player
positions, rendered onto aerial pitches with mplsoccer.

Data access, fastest first:
  1. Direct API calls through datafc's curl_cffi client (Chrome TLS
     impersonation) against the Sofascore mirrors — sub-second per endpoint.
  2. Browser harvesting via ScraperFC's botasaurus stack: load the real match
     page and capture the JSON the page fetches. Slow but nearly unblockable.

Modes:
    sofascore_live.py             one pass over matches near now
    sofascore_live.py --watch 20  stay running while matches are live:
                                  refresh everything every ~20s, patch the
                                  live score in data.json, redraw pitches and
                                  mirror docs/ to the Mac mini. Exits when no
                                  match is live.

Outputs:
    docs/sofascore.json        {espn_match_id: {incidents, lineups, stats,
                                momentum, shots, positions, pitch, shotmap_img,
                                sofa_id, updated}}
    docs/img/pitch_<id>.png    average-positions pitch (mplsoccer)
    docs/img/shots_<id>.png    shotmap, marker size = xG (mplsoccer)

Fails soft everywhere: a blocked source or missing dependency just means
that piece of data is skipped this run.
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
SOFA_BASES = ["https://api.sofavpn.com", "https://www.sofascore.com", "https://api.sofascore.com"]
WC_TOURNAMENT_ID = 16
# real-time channel to the public site: each watch cycle pushes the live score,
# clock, feed and stats here; index.html subscribes over SSE (GitHub Pages only
# refreshes on git pushes, which are capped — this sidesteps that entirely)
NTFY_LIVE = "https://ntfy.sh/wc26-sweepstake-live-spridge-k7q4x9"
# How long the persistent watcher sleeps between polls when nothing is live
# (one cheap ESPN scoreboard call per tick to notice the next kick-off).
WATCH_IDLE_INTERVAL = 30

try:
    from datafc.utils._client import SofascoreClient
    HAVE_API = True
except ImportError:
    HAVE_API = False

try:
    from botasaurus.browser import browser, Driver
    HAVE_BROWSER = True
except ImportError:
    HAVE_BROWSER = False

if not HAVE_API and not HAVE_BROWSER:
    sys.exit("Install at least one data path: pip3 install datafc  (or ScraperFC)")


def normalize(name):
    name = unicodedata.normalize("NFKD", str(name))
    return "".join(c for c in name.lower() if c.isalpha())


# --------------------------------------------------------------- API access

_client = None


def sofa_get(path):
    """GET a Sofascore API path, trying each mirror. Raises on total failure."""
    global _client
    if _client is None:
        _client = SofascoreClient(rate_limit=4.0)
    last = None
    for base in SOFA_BASES:
        try:
            return _client.get(f"{base}/api/v1{path}")
        except Exception as e:
            last = e
            if "404" in str(e):       # endpoint exists, data doesn't — stop here
                break
    raise last


# ----------------------------------------------------------- target matching

def load_targets():
    """Matches near now from our own data.json: {frozenset(codes): espn_id}."""
    data = json.loads((DOCS / "data.json").read_text())
    name_to_code = {}
    variants = {}
    for code, t in data["teams"].items():
        variants[code] = {normalize(t["name"]), normalize(code)}
        name_to_code[normalize(t["name"])] = code
    for t in json.loads((ROOT / "data/teams.json").read_text())["teams"]:
        variants[t["code"]].update(normalize(a) for a in t.get("aliases", []))

    # matches that already have a captured attack-momentum graph, so finished
    # games still missing it keep getting retried (Sofascore can lag, and old
    # matches otherwise fall out of the time window before momentum lands)
    try:
        have_momentum = set()
        for k, v in json.loads((DOCS / "sofascore.json").read_text()).items():
            mom = v.get("momentum") or []
            if mom and max((p.get("m", 0) for p in mom), default=0) >= 85:  # full-match graph
                have_momentum.add(int(k))
    except Exception:
        have_momentum = set()

    now = datetime.now(timezone.utc)
    targets = {}
    codes_by_id = {}
    result_ids = {r["id"] for r in (data.get("results") or []) if r.get("id")}
    rows = (list(data.get("live") or []) + list(data.get("results") or [])
            + list(data.get("upcoming") or []))
    for r in rows:
        utc = r.get("utc")
        if not utc or not r.get("id"):
            continue
        when = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        in_window = now - timedelta(hours=WINDOW_BACK_H) <= when <= now + timedelta(hours=WINDOW_FWD_H)
        retry_momentum = r["id"] in result_ids and r["id"] not in have_momentum
        if not in_window and not retry_momentum:
            continue
        hc = r["home"].get("code") or name_to_code.get(normalize(r["home"]["name"]))
        ac = r["away"].get("code") or name_to_code.get(normalize(r["away"]["name"]))
        if hc and ac:
            targets[frozenset((hc, ac))] = r["id"]
            codes_by_id[r["id"]] = (hc, ac)
    live_ids = {m["id"] for m in data.get("live") or []}
    return targets, variants, data["teams"], live_ids, codes_by_id


def code_for(name, variants):
    n = normalize(name)
    for code, vs in variants.items():
        if n in vs:
            return code
    return None


def api_find_matches(targets, variants):
    """{espn_id: (sofa_event_id, (home_code, away_code))} via the schedule API."""
    found = {}
    today = datetime.now(timezone.utc)
    for day in (today, today + timedelta(days=1)):
        try:
            events = sofa_get(f"/sport/football/scheduled-events/{day:%Y-%m-%d}").get("events", [])
        except Exception as e:
            print(f"  schedule {day:%Y-%m-%d} failed ({e})")
            continue
        for e in events:
            ut = ((e.get("tournament") or {}).get("uniqueTournament") or {})
            if ut.get("id") != WC_TOURNAMENT_ID:
                continue
            hc = code_for((e.get("homeTeam") or {}).get("name", ""), variants)
            ac = code_for((e.get("awayTeam") or {}).get("name", ""), variants)
            espn_id = targets.get(frozenset((hc, ac))) if hc and ac else None
            if espn_id and espn_id not in found:
                found[espn_id] = (str(e["id"]), (hc, ac))
    return found


# ------------------------------------------------------------ browser fallback

if HAVE_BROWSER:
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
        for frac in (0.4, 0.8):    # lazy sections load when scrolled into view
            driver.run_js(f"window.scrollTo(0, document.body.scrollHeight*{frac})")
            driver.sleep(1.5 if quick else 2)
        out = {}
        for rid, u in list(hits.items()):
            key = u.split("/api/v1/")[1].split("?")[0]
            short = next((k for k in ("incidents", "lineups", "average-positions",
                                      "statistics", "graph", "shotmap")
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

    def slug_to_codes(slug, variants):
        s = normalize(slug.replace("-", ""))
        for ca, va in variants.items():
            for a in sorted(va, key=len, reverse=True):
                if a and s.startswith(a):
                    rest = s[len(a):]
                    for cb, vb in variants.items():
                        if cb != ca and rest in vb:
                            return ca, cb
        return None, None

    def browser_find_matches(targets, variants):
        """{espn_id: (link, (codeA, codeB))} from the live/date pages."""
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


# ----------------------------------------------------------------- parsers

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
    "Expected goals": "xg",
    "Big chances": "big_chances",
    "Total shots": "shots",
    "Shots on target": "shots_on_goal",
    "Shots off target": "shots_off_goal",
    "Blocked shots": "blocked_shots",
    "Hit woodwork": "woodwork",
    "Corner kicks": "corner_kicks",
    "Free kicks": "free_kicks",
    "Fouls": "fouls",
    "Passes": "passes",
    "Long balls": "long_balls",
    "Crosses": "crosses",
    "Tackles": "tackles",
    "Interceptions": "interceptions",
    "Clearances": "clearances",
    "Throw-ins": "throw_ins",
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


def parse_momentum(raw):
    """Attack momentum: [{m: minute, v: -100..100}] — positive = home pressure."""
    pts = [{"m": round(p.get("minute", 0), 1), "v": p.get("value", 0)}
           for p in raw.get("graphPoints") or raw.get("graph") or []
           if p.get("minute") is not None]
    return pts or None


def parse_shots(raw):
    out = []
    for s in raw.get("shotmap") or []:
        c = s.get("playerCoordinates") or {}
        out.append({
            "player": (s.get("player") or {}).get("shortName"),
            "team": "home" if s.get("isHome") else "away",
            "type": s.get("shotType"),               # goal / save / miss / block / post
            "xg": round(s["xg"], 2) if s.get("xg") is not None else None,
            "x": c.get("x"), "y": c.get("y"),
            "minute": s.get("time"),
        })
    return out or None


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


# ------------------------------------------------------------------ rendering

def render(mode, path, home, away, payload):
    """Render a pitch PNG via render_pitch.py in the mplsoccer venv (>=3.10)."""
    import os
    import tempfile

    candidates = [os.environ.get("PITCH_PYTHON"),
                  str(ROOT / ".venv-pitch/bin/python"),
                  sys.executable]
    py = next((c for c in candidates if c and Path(c).exists()), None)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        tmp = f.name
    try:
        subprocess.run([py, str(ROOT / "scripts/render_pitch.py"), tmp, str(path),
                        home, away, mode], check=True, capture_output=True, timeout=120)
    finally:
        os.unlink(tmp)


def apply_payloads(ent, payloads, espn_id, codes, teams):
    """Fold raw endpoint payloads into a sofascore.json entry."""
    ca, cb = codes
    home = teams.get(ca, {}).get("name", ca)
    away = teams.get(cb, {}).get("name", cb)
    if payloads.get("incidents"):
        ent["incidents"] = parse_incidents(payloads["incidents"])
    if payloads.get("lineups"):
        ent["lineups"] = parse_lineups(payloads["lineups"])
    if payloads.get("statistics"):
        stats = parse_statistics(payloads["statistics"])
        if stats:
            ent["stats"] = stats
    if payloads.get("graph"):
        momentum = parse_momentum(payloads["graph"])
        if momentum:
            cover = lambda arr: max((p.get("m", 0) for p in arr), default=0)
            if cover(momentum) >= cover(ent.get("momentum") or []):   # never truncate a fuller graph
                ent["momentum"] = momentum
    if payloads.get("shotmap"):
        shots = parse_shots(payloads["shotmap"])
        if shots:
            ent["shots"] = shots
            img = IMG / f"shots_{espn_id}.png"
            try:
                render("shots", img, home, away, {"shots": shots})
                ent["shotmap_img"] = f"img/shots_{espn_id}.png"
            except Exception as e:
                print(f"  shotmap render failed ({e})")
    if payloads.get("average-positions"):
        pos = parse_positions(payloads["average-positions"])
        if pos.get("home") or pos.get("away"):
            ent["positions"] = pos
            img = IMG / f"pitch_{espn_id}.png"
            try:
                render("positions", img, home, away, pos)
                ent["pitch"] = f"img/pitch_{espn_id}.png"
            except Exception as e:
                print(f"  pitch render failed ({e})")
    return [k for k in ("incidents", "lineups", "stats", "momentum", "shots",
                        "positions", "pitch") if ent.get(k)]


# Order matters: fetch the light, time-critical live endpoints first (events,
# momentum, stats) so that if Sofascore cuts us off with a 403 part-way through a
# cycle, the data players actually watch has already been captured. The heavy
# shotmap/average-positions come last and are throttled (see harvest_api).
API_ENDPOINTS = {
    "incidents": "incidents",
    "graph": "graph",
    "statistics": "statistics",
    "lineups": "lineups",
    "shotmap": "shotmap",
    "average-positions": "average-positions",
}
HEAVY_REFRESH = 90        # seconds between shotmap/average-positions fetches while live


def harvest_api(espn_id, sofa_id, codes, teams, out, live=False):
    ent = out.get(str(espn_id), {})
    # keep the request volume low so Sofascore doesn't rate-limit/403 us: capture
    # the static endpoints once, but keep the evolving ones fresh while live.
    skip = set()
    if ent.get("lineups"):                       # confirmed line-ups don't change
        skip.add("lineups")
    # Shots and average positions keep changing through a match (a late goal is a
    # new shot; positions drift), so we never freeze them mid-match — BUT we only
    # refresh them every HEAVY_REFRESH seconds, not every cycle. Hammering all
    # six endpoints every ~12s trips Sofascore's 403 rate-limit, which also kills
    # the data players care about most (momentum & stats). Once the match is over
    # we stop refreshing them entirely. Timestamps live on the entry so the
    # 12s watcher and the 46s git updater share one throttle.
    now = time.time()
    for short, key in (("shotmap", "shots"), ("average-positions", "positions")):
        if not ent.get(key):
            continue                             # never captured yet — always try
        stale = now - ent.get("_heavy_at", {}).get(short, 0)
        if not live or stale < HEAVY_REFRESH:
            skip.add(short)
    payloads = {}
    for short, ep in API_ENDPOINTS.items():
        if short in skip:
            continue
        try:
            payloads[short] = sofa_get(f"/event/{sofa_id}/{ep}")
        except Exception:
            pass
        if short in ("shotmap", "average-positions"):
            ent.setdefault("_heavy_at", {})[short] = now    # mark the attempt (success or 403) to throttle
    ent.update({"sofa_id": str(sofa_id),
                "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    got = apply_payloads(ent, payloads, espn_id, codes, teams)
    out[str(espn_id)] = ent
    return got


def harvest_browser(link, espn_id, codes, teams, out, quick=False):
    payloads = capture_match({"url": link, "quick": quick})
    ent = out.get(str(espn_id), {})
    sofa_id = re.search(r"#id:(\d+)", link)
    ent.update({"sofa_id": sofa_id.group(1) if sofa_id else None,
                "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    got = apply_payloads(ent, payloads, espn_id, codes, teams)
    out[str(espn_id)] = ent
    return got


def find_and_harvest(targets, variants, teams, out, only_ids=None, quick=False,
                     codes_by_id=None, live_ids=None):
    """Try the fast API path; fall back to the browser. Returns set harvested."""
    done = set()
    codes_by_id = codes_by_id or {}
    live_ids = set(live_ids or ())
    wanted = set(targets.values()) if only_ids is None else set(only_ids)
    # 1) Direct harvest by the sofa_id we already stored — this keeps live matches
    #    updating even when Sofascore blocks the discovery endpoint (HTTP 403).
    if HAVE_API:
        for espn_id in wanted:
            sofa_id = (out.get(str(espn_id)) or {}).get("sofa_id")
            codes = codes_by_id.get(espn_id)
            if not sofa_id or not codes:
                continue
            try:
                got = harvest_api(espn_id, sofa_id, codes, teams, out,
                                  live=espn_id in live_ids)
                print(f"  [direct] match {espn_id}: {', '.join(got) or 'nothing'}")
                done.add(espn_id)
            except Exception as e:
                print(f"  [direct] match {espn_id} failed ({e})")
    # 2) Discovery for anything we don't yet know the sofa_id of (new matches)
    if HAVE_API and (wanted - done):
        try:
            found = api_find_matches(targets, variants)
        except Exception as e:
            print(f"  API discovery failed ({e})")
            found = {}
        for espn_id, (sofa_id, codes) in found.items():
            if espn_id in done or (only_ids is not None and espn_id not in only_ids):
                continue
            got = harvest_api(espn_id, sofa_id, codes, teams, out,
                              live=espn_id in live_ids)
            print(f"  [api] match {espn_id}: {', '.join(got) or 'nothing yet'}")
            done.add(espn_id)
    missing = wanted - done
    if missing and HAVE_BROWSER:
        print(f"  browser fallback for {len(missing)} match(es)")
        found = browser_find_matches(targets, variants)
        for espn_id, (link, codes) in found.items():
            if espn_id not in missing:
                continue
            got = harvest_browser(link, espn_id, codes, teams, out, quick=quick)
            print(f"  [browser] match {espn_id}: {', '.join(got) or 'nothing yet'}")
            done.add(espn_id)
    return done


# ------------------------------------------------------------ live score patch

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
        atomic_write(path, json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        print("  patched live scores in data.json")


def reconcile_live_scores(out):
    """Race ESPN against Sofascore: bump each live match's score to whichever
    source is ahead, so a goal shows the moment EITHER reports it. data.json
    already holds the ESPN score (from espn_quick_scores / update_scores); here
    we compare it to the Sofascore goals we just harvested and take the higher
    total. Self-correcting — if a goal is later disallowed (VAR) and a source
    drops it, the totals re-converge and the score steps back next cycle."""
    path = DOCS / "data.json"
    try:
        data = json.loads(path.read_text())
    except Exception:
        return
    changed = False
    for m in data.get("live") or []:
        ent = out.get(str(m.get("id"))) or {}
        goals = [i for i in (ent.get("incidents") or []) if i.get("type") == "goal"]
        if not goals:
            continue
        last = goals[-1]
        sh, sa = last.get("homeScore"), last.get("awayScore")
        if sh is None or sa is None:                 # fall back to counting goals per side
            sh = sum(1 for g in goals if g.get("team") == "home")
            sa = sum(1 for g in goals if g.get("team") == "away")
        eh, ea = m["home"]["goals"], m["away"]["goals"]
        if (sh + sa) > (eh + ea):                    # Sofascore is ahead — adopt its scoreline
            m["home"]["goals"], m["away"]["goals"] = sh, sa
            changed = True
            print(f"  match {m['id']}: Sofascore ahead {sh}-{sa} (ESPN {eh}-{ea})")
    if changed:
        data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        atomic_write(path, json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def _ntfy_post(body):
    try:
        req = urllib.request.Request(NTFY_LIVE, data=body.encode("utf-8"), method="POST")
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"  live relay publish failed ({e})")
        return False


# remember the last state we published per match so we only hit the relay when
# something meaningful changes (publishing every cycle trips ntfy's rate limit)
_LAST_PUBLISHED = {}


def publish_live_updates(out, prev_live_ids, live_ids):
    """Push fresh live data to the relay so the public page updates in ~20s."""
    try:
        data = json.loads((DOCS / "data.json").read_text())
    except Exception:
        return
    by_id = {m["id"]: m for m in data.get("live") or []}
    for mid in live_ids:
        m = by_id.get(mid)
        if not m:
            continue
        ent = out.get(str(mid), {})
        # Only the score and the events matter for the relay — the client ticks
        # the clock itself and re-syncs it from the 15s git poll, so we DON'T
        # publish on clock-minute changes. That keeps relay traffic down to a
        # handful of messages per match (goals/cards/subs) — well under ntfy's
        # rate limit, which the old every-cycle publishing was tripping (429).
        sig = (m["home"]["goals"], m["away"]["goals"], len(ent.get("incidents") or []))
        if _LAST_PUBLISHED.get(mid) == sig:       # score and events unchanged — skip
            continue
        payload = {"id": mid, "live": m,
                   "incidents": (ent.get("incidents") or [])[-8:],
                   "stats": ent.get("stats")}
        body = json.dumps(payload, ensure_ascii=False)
        if len(body) > 3900:                      # ntfy message cap
            payload["incidents"] = (payload["incidents"] or [])[-3:]
            payload["stats"] = None
            body = json.dumps(payload, ensure_ascii=False)
        _ntfy_post(body)
        _LAST_PUBLISHED[mid] = sig                # mark attempted regardless — never hammer on failure
    for mid in prev_live_ids - live_ids:
        _ntfy_post(json.dumps({"id": mid, "ended": True}))
        _LAST_PUBLISHED.pop(mid, None)


def mirror_to_mini():
    try:
        subprocess.run(
            ["rsync", "-a", "--exclude", ".DS_Store", "--exclude", "*.tmp",
             str(DOCS) + "/", "macmini:worldcup-sweepstake/docs/"],
            capture_output=True, timeout=60)
    except Exception as e:
        print(f"  mirror to mini failed ({e}); continuing")


def atomic_write(path, text):
    """A reader (or the web server) must never see a half-written file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def write_out(out):
    atomic_write(DOCS / "sofascore.json", json.dumps(out, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------- modes

def backfill_momentum(out):
    """Fetch attack-momentum directly via stored sofa_id for finished matches that
    are missing it — discovery can't find old games on Sofascore's current pages."""
    if not HAVE_API:
        return
    try:
        result_ids = {r["id"] for r in
                      json.loads((DOCS / "data.json").read_text()).get("results") or [] if r.get("id")}
    except Exception:
        return
    for espn_id, ent in list(out.items()):
        if not ent.get("sofa_id"):
            continue
        cur = ent.get("momentum") or []
        if max((p.get("m", 0) for p in cur), default=0) >= 85:
            continue                                   # already a full-match graph
        try:
            if int(espn_id) not in result_ids:
                continue
            mom = parse_momentum(sofa_get(f"/event/{ent['sofa_id']}/graph"))
        except Exception:
            continue
        if mom and len(mom) > len(cur):                # only replace with a more complete graph
            ent["momentum"] = mom
            ent["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(f"  [backfill] momentum for match {espn_id}: {len(mom)} pts")


def main():
    targets, variants, teams, live_ids, codes_by_id = load_targets()
    sofa_path = DOCS / "sofascore.json"
    out = json.loads(sofa_path.read_text()) if sofa_path.exists() else {}
    IMG.mkdir(exist_ok=True)
    if targets:
        print(f"Harvesting {len(targets)} match(es) "
              f"({'API-first' if HAVE_API else 'browser only'})...")
        find_and_harvest(targets, variants, teams, out, codes_by_id=codes_by_id, live_ids=live_ids)
    reconcile_live_scores(out)            # take whichever of ESPN/Sofascore is ahead
    backfill_momentum(out)
    write_out(out)
    print(f"Wrote docs/sofascore.json ({len(out)} matches)")


def watch(interval):
    """Stay running while matches are live; refresh every `interval` seconds."""
    print(f"Watch mode: refreshing live matches every ~{interval}s "
          f"({'API-first' if HAVE_API else 'browser only'})")
    sofa_path = DOCS / "sofascore.json"
    out = json.loads(sofa_path.read_text()) if sofa_path.exists() else {}
    IMG.mkdir(exist_ok=True)
    prev_live_ids = set()
    while True:
        cycle_start = time.time()
        espn_quick_scores()
        targets, variants, teams, live_ids, codes_by_id = load_targets()
        if not live_ids:
            if prev_live_ids:                       # a match just ended — tell the relay
                publish_live_updates(out, prev_live_ids, set())
                prev_live_ids = set()
            # Stay alive and poll cheaply for the next kick-off instead of exiting.
            # A persistent watcher keeps the real-time relay ready the instant a
            # match goes live, rather than waiting up to 5 min to be respawned.
            time.sleep(WATCH_IDLE_INTERVAL)
            continue
        find_and_harvest(targets, variants, teams, out, only_ids=live_ids, quick=True, codes_by_id=codes_by_id, live_ids=live_ids)
        reconcile_live_scores(out)        # take whichever of ESPN/Sofascore is ahead
        write_out(out)
        mirror_to_mini()
        publish_live_updates(out, prev_live_ids, live_ids)
        prev_live_ids = set(live_ids)
        time.sleep(max(5, interval - (time.time() - cycle_start)))


if __name__ == "__main__":
    if "--watch" in sys.argv:
        idx = sys.argv.index("--watch")
        secs = int(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 and sys.argv[idx + 1].isdigit() else 20
        watch(secs)
    else:
        main()
