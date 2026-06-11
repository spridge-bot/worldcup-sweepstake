#!/usr/bin/env python3
"""Sofascore live layer: minute-by-minute incidents, confirmed line-ups and
average player positions for matches around now, rendered onto an aerial
pitch with mplsoccer.

Uses ScraperFC's bundled botasaurus browser. Sofascore's API challenges
direct requests, so we load the real match pages and harvest the JSON
responses the page itself fetches (incidents / lineups / average-positions).

Outputs:
    docs/sofascore.json        {espn_match_id: {incidents, lineups, positions,
                                pitch, sofa_id, updated}}
    docs/img/pitch_<id>.png    aerial average-position pitch view (mplsoccer)

Fails soft: any missing dependency or blocked request leaves the existing
files untouched. Run it as often as you like (a few minutes apart) while
matches are on.
"""
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
IMG = DOCS / "img"
WINDOW_BACK_H = 8     # cover matches that finished earlier today
WINDOW_FWD_H = 12     # and ones kicking off soon (line-ups confirm ~1h before)

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
        names = {t["name"], code}
        variants[code] = {normalize(n) for n in names}
        name_to_code[normalize(t["name"])] = code
    # teams.json aliases give better slug matching (e.g. cote-divoire)
    for t in json.loads((ROOT / "data/teams.json").read_text())["teams"]:
        variants[t["code"]].update(normalize(a) for a in t.get("aliases", []))

    now = datetime.now(timezone.utc)
    targets = {}
    rows = list(data.get("live") or [])
    rows += [r for r in data.get("results") or []]
    rows += [u for u in data.get("upcoming") or []]
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
    return targets, variants, data["teams"]


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
def capture_match(driver: Driver, url):
    """Open a match page and harvest the API JSON the page fetches."""
    import base64
    hits = {}

    def handler(request_id, response, event):
        if "/api/v1/event/" in response.url:
            hits[request_id] = response.url

    driver.after_response_received(handler)
    driver.get(url)
    driver.sleep(7)
    for frac in (0.4, 0.8):    # average-positions loads when scrolled into view
        driver.run_js(f"window.scrollTo(0, document.body.scrollHeight*{frac})")
        driver.sleep(2)
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
    import subprocess
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


def main():
    targets, variants, teams = load_targets()
    if not targets:
        print("No matches within the live window; nothing to do.")
        return
    print(f"Looking for {len(targets)} match(es) on Sofascore...")

    today = datetime.now(timezone.utc)
    urls = ["https://www.sofascore.com/football/livescore",
            f"https://www.sofascore.com/football/{today:%Y-%m-%d}"]
    links = discover_links({"urls": urls})

    sofa_path = DOCS / "sofascore.json"
    out = json.loads(sofa_path.read_text()) if sofa_path.exists() else {}
    IMG.mkdir(exist_ok=True)

    seen = set()
    for link in links:
        m = re.search(r"/football/match/([a-z0-9-]+)/[A-Za-z]+#id:(\d+)", link)
        if not m:
            continue
        slug, sofa_id = m.group(1), m.group(2)
        if sofa_id in seen:
            continue
        seen.add(sofa_id)
        ca, cb = slug_to_codes(slug, variants)
        espn_id = targets.get(frozenset((ca, cb))) if ca and cb else None
        if not espn_id:
            continue
        print(f"  {slug} (sofa {sofa_id}) -> match {espn_id}")
        payloads = capture_match(link)
        ent = out.get(str(espn_id), {})
        ent.update({"sofa_id": sofa_id,
                    "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        if payloads.get("incidents"):
            ent["incidents"] = parse_incidents(payloads["incidents"])
        if payloads.get("lineups"):
            ent["lineups"] = parse_lineups(payloads["lineups"])
        if payloads.get("average-positions"):
            pos = parse_positions(payloads["average-positions"])
            if pos.get("home") or pos.get("away"):
                ent["positions"] = pos
                home = teams.get(ca, {}).get("name", ca)
                away = teams.get(cb, {}).get("name", cb)
                img = IMG / f"pitch_{espn_id}.png"
                try:
                    draw_pitch(img, home, away, pos)
                    ent["pitch"] = f"img/pitch_{espn_id}.png"
                except Exception as e:
                    print(f"  pitch render failed ({e})")
        out[str(espn_id)] = ent
        got = [k for k in ("incidents", "lineups", "positions", "pitch") if ent.get(k)]
        print(f"    captured: {', '.join(got) or 'nothing yet'}")

    sofa_path.write_text(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"Wrote docs/sofascore.json ({len(out)} matches)")


if __name__ == "__main__":
    main()
