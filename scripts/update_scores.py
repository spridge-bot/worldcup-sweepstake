#!/usr/bin/env python3
"""Fetch World Cup 2026 results, score the sweepstake, write docs/data.json.

Usage:
    FOOTBALL_DATA_TOKEN=xxx python scripts/update_scores.py   # live results
    python scripts/update_scores.py --offline                 # no results yet, just render the draw
    python scripts/update_scores.py --demo                    # fake results to preview the scoring

Get a free API token at https://www.football-data.org/client/register
(the free tier includes the FIFA World Cup).

Outputs:
    docs/data.json     leaderboard, results, group tables, top scorers
    docs/details.json  per-match detail (goals, cards, subs, lineups, stats),
                       built up incrementally across runs because the free API
                       tier allows 10 requests/minute.

Scoring (see data/scoring.json for the tunable numbers):
  Balance comes from the draw (each player holds one team from each tier),
  so points are flat — no multipliers.
  - Group stage: finish 1st in your group 5, 2nd 3, 3rd 1, 4th 0.
    Positions are scored LIVE as group games finish and lock in when the
    group completes (the average team earns ~2.25 points).
  - Knockout: win your Round-of-32 tie 2, R16 3, QF 4, SF 5, the final 6.
    Shootout wins count as wins. (Third-place play-off carries no points.)
"""
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_BASE = "https://api.football-data.org/v4"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"
ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer/fifa.world/standings"
BBC_WC_NEWS = "https://feeds.bbci.co.uk/sport/football/world-cup/rss.xml"
# BBC interactive/promo items that aren't actual news — matched against the
# lower-cased headline and skipped (the video/audio pages are dropped by link).
NEWS_SKIP_TITLE = (
    "how to watch", "without any spoilers", "only on bbc sport",
    "bbc sport has an app", "set up bbc sport", "take our quiz",
    "world cup quiz", "who am i?", "guess world cup star",
    "which world cup team are you", "predictor game", "name these",
)
WC_START = datetime(2026, 6, 11)
WC_END = datetime(2026, 7, 19)
ESPN_SUMMARY_CAP = 30   # max match summaries to pull per run
DETAIL_FETCH_CAP = 25      # max match-detail requests per run
DETAIL_FETCH_PAUSE = 6.5   # seconds between requests (free tier: 10/min)

KNOCKOUT_STAGES = ["LAST_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "THIRD_PLACE", "FINAL"]
STAGE_LABELS = {
    "GROUP_STAGE": "Group stage",
    "LAST_32": "Round of 32",
    "LAST_16": "Round of 16",
    "QUARTER_FINALS": "Quarter-final",
    "SEMI_FINALS": "Semi-final",
    "THIRD_PLACE": "Third-place play-off",
    "FINAL": "Final",
}


def normalize(name):
    """'Côte d'Ivoire' -> 'cotedivoire' so API names match ours."""
    name = unicodedata.normalize("NFKD", name)
    return "".join(c for c in name.lower() if c.isalpha())


def load_json(rel):
    return json.loads((ROOT / rel).read_text())


def write_json(path, obj, indent=None):
    """Atomic write: a reader (or the web server) never sees a half-written file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=indent, ensure_ascii=False) + "\n")
    tmp.replace(path)


def build_team_index(teams):
    index = {}
    for t in teams:
        index[normalize(t["name"])] = t["code"]
        index[t["code"].lower()] = t["code"]
        for alias in t.get("aliases", []):
            index[normalize(alias)] = t["code"]
    return index


def resolve_team(index, api_team):
    """Map an API team object to our 3-letter code, or None (e.g. TBD placeholders)."""
    if not api_team:
        return None
    if isinstance(api_team, str):
        return index.get(normalize(api_team))
    for field in ("name", "shortName", "tla", "displayName", "shortDisplayName", "abbreviation"):
        key = api_team.get(field)
        if key and normalize(key) in index:
            return index[normalize(key)]
    return None


def fetch_json(url, token):
    req = urllib.request.Request(url, headers={"X-Auth-Token": token})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_matches(token):
    return fetch_json(f"{API_BASE}/competitions/WC/matches", token)["matches"]


def fetch_scorers(token, index, teams_by_code, owner):
    """Golden Boot standings — one cheap request, fail soft."""
    try:
        data = fetch_json(f"{API_BASE}/competitions/WC/scorers?limit=15", token)
    except Exception as e:
        print(f"  scorers fetch failed ({e}); skipping")
        return []
    out = []
    for s in data.get("scorers", []):
        code = resolve_team(index, s.get("team"))
        out.append({
            "player": s.get("player", {}).get("name", "?"),
            "team": code,
            "flag": teams_by_code[code]["flag"] if code else "",
            "owner": owner.get(code) if code else None,
            "goals": s.get("goals") or 0,
            "assists": s.get("assists") or 0,
        })
    return out


# ---------------------------------------------------------------- odds (ESPN)

def american_to_decimal(american):
    """-240 -> 1.42, +750 -> 8.50 (decimal odds are easier to read)."""
    try:
        v = int(str(american).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    if v < 0:
        return round(1 + 100 / abs(v), 2)
    return round(1 + v / 100, 2)


def parse_espn_odds(comp):
    """1X2 + over/under decimal odds from an ESPN competition object, or None."""
    odds = (comp.get("odds") or [None])[0] or {}
    ml = odds.get("moneyline") or {}

    def closing(side):
        return american_to_decimal((((ml.get(side) or {}).get("close")) or {}).get("odds"))

    h, a = closing("home"), closing("away")
    draw_ml = (odds.get("drawOdds") or {}).get("moneyLine")
    d = american_to_decimal(draw_ml) if draw_ml is not None else None
    if not (h or a or d):
        return None
    return {
        "home": h, "draw": d, "away": a,
        "over_under": odds.get("overUnder"),
        "provider": (odds.get("provider") or {}).get("displayName") or "DraftKings",
    }


def fetch_espn_extras(index):
    """Odds + recent form for upcoming fixtures from ESPN's public scoreboard API.

    Free, no key needed. Returns {(date, {home,away} codes): {odds, form}}.
    Fails soft — the sweepstake works fine without it.
    """
    start = datetime.now(timezone.utc)
    rng = f"{start:%Y%m%d}-{start + timedelta(days=10):%Y%m%d}"
    try:
        data = espn_get(f"{ESPN_SCOREBOARD}?dates={rng}")
    except Exception as e:
        print(f"  ESPN odds fetch failed ({e}); skipping")
        return {}

    out = {}
    for e in data.get("events", []):
        c = (e.get("competitions") or [{}])[0]
        comps = c.get("competitors") or []
        home = next((t for t in comps if t.get("homeAway") == "home"), None)
        away = next((t for t in comps if t.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        hc = resolve_team(index, home.get("team"))
        ac = resolve_team(index, away.get("team"))
        if not hc or not ac:
            continue
        entry = {"form": {hc: home.get("form"), ac: away.get("form")}}
        odds = parse_espn_odds(c)
        if odds:
            entry["odds"] = odds
        out[(e.get("date") or "")[:10], frozenset((hc, ac))] = entry
    found = sum(1 for v in out.values() if "odds" in v)
    print(f"  ESPN: odds for {found} of {len(out)} upcoming fixtures")
    return out


# ------------------------------------------------- ESPN match-stats enrichment

ESPN_STAT_MAP = {
    "possessionPct": "ball_possession",
    "totalShots": "shots",
    "shotsOnTarget": "shots_on_goal",
    "wonCorners": "corner_kicks",
    "foulsCommitted": "fouls",
    "offsides": "offsides",
    "saves": "saves",
    "yellowCards": "yellow_cards",
    "redCards": "red_cards",
    "totalPasses": "passes",
    "passPct": "pass_accuracy",
    "totalCrosses": "crosses",
    "totalLongBalls": "long_balls",
}


def espn_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_news(limit=12):
    """Real World Cup stories from the BBC Sport RSS feed. These are text
    articles on bbc.co.uk (readable from locked-down work networks, unlike the
    ESPN pages that are built around video). Returns
    [{headline, desc, link, published, type, image, source}] — never fabricated."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    try:
        req = urllib.request.Request(BBC_WC_NEWS, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            root = ET.fromstring(resp.read())
    except Exception as e:
        print(f"  news fetch skipped: {e}")
        return []
    THUMB = "{http://search.yahoo.com/mrss/}thumbnail"
    out = []
    for it in root.findall("./channel/item"):
        headline = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not headline or not link:
            continue
        if any(seg in link for seg in ("/av/", "/videos/", "/sounds/")):   # video/audio
            continue
        if any(p in headline.lower() for p in NEWS_SKIP_TITLE):            # promos/quizzes
            continue
        # RFC-822 pubDate -> ISO-8601 UTC so the page's "x ago" math keeps working
        published = None
        raw = it.findtext("pubDate")
        if raw:
            try:
                published = (parsedate_to_datetime(raw).astimezone(timezone.utc)
                             .isoformat(timespec="seconds").replace("+00:00", "Z"))
            except Exception:
                pass
        thumb = it.find(THUMB)
        image = thumb.get("url") if thumb is not None else None
        if image and "/standard/" in image:              # bump 240px thumb -> crisper 480px
            pre, _, rest = image.partition("/standard/")
            num, _, tail = rest.partition("/")
            if num.isdigit():
                image = f"{pre}/standard/480/{tail}"
        out.append({
            "headline": headline,
            "desc": (it.findtext("description") or "").strip(),
            "link": link,
            "published": published,
            "type": "Story",
            "image": image,
            "source": "BBC Sport",
        })
        if len(out) >= limit:
            break
    return out


def espn_event_map(dates, index):
    """{(utc date, {home,away} codes): espn event id} for the given match dates."""
    if not dates:
        return {}
    out = {}
    days = sorted(dates)
    cur = datetime.strptime(days[0], "%Y-%m-%d") - timedelta(days=1)
    last = datetime.strptime(days[-1], "%Y-%m-%d") + timedelta(days=1)
    while cur <= last:
        end = min(cur + timedelta(days=6), last)
        try:
            data = espn_get(f"{ESPN_SCOREBOARD}?dates={cur:%Y%m%d}-{end:%Y%m%d}")
        except Exception as e:
            print(f"  ESPN scoreboard fetch failed ({e})")
            cur = end + timedelta(days=1)
            continue
        for e in data.get("events", []):
            c = (e.get("competitions") or [{}])[0]
            comps = c.get("competitors") or []
            home = next((t for t in comps if t.get("homeAway") == "home"), None)
            away = next((t for t in comps if t.get("homeAway") == "away"), None)
            hc = resolve_team(index, (home or {}).get("team"))
            ac = resolve_team(index, (away or {}).get("team"))
            if hc and ac:
                out[(e.get("date") or "")[:10], frozenset((hc, ac))] = e.get("id")
        cur = end + timedelta(days=1)
    return out


def merge_espn_summary(ent, summary, index):
    """Fold ESPN boxscore stats / rosters / game info into a cached match detail."""
    side_by_code = {ent["home"].get("code"): ent["home"], ent["away"].get("code"): ent["away"]}

    for t in (summary.get("boxscore") or {}).get("teams") or []:
        side = side_by_code.get(resolve_team(index, t.get("team")))
        if not side:
            continue
        stats = side.setdefault("stats", {})
        for st in t.get("statistics") or []:
            key = ESPN_STAT_MAP.get(st.get("name"))
            if not key:
                continue
            try:
                num = float(st.get("displayValue"))
            except (TypeError, ValueError):
                continue
            if st["name"] == "passPct" and num <= 1:
                num *= 100
            stats[key] = int(num) if num == int(num) else round(num, 1)   # update so live stats stay current

    for r in summary.get("rosters") or []:
        side = side_by_code.get(resolve_team(index, r.get("team")))
        if not side:
            continue
        if not side.get("formation"):
            side["formation"] = r.get("formation")
        if not side.get("lineup"):
            def pl(p):
                return {"name": (p.get("athlete") or {}).get("displayName", "?"),
                        "position": (p.get("position") or {}).get("displayName"),
                        "shirt": p.get("jersey")}
            entries = r.get("roster") or []
            starters = sorted((p for p in entries if p.get("starter")),
                              key=lambda p: int(p.get("formationPlace") or 99))
            side["lineup"] = [pl(p) for p in starters]
            side["bench"] = [pl(p) for p in entries if not p.get("starter")]

    info = summary.get("gameInfo") or {}
    ent["venue"] = ent.get("venue") or (info.get("venue") or {}).get("fullName")
    ent["attendance"] = ent.get("attendance") or info.get("attendance")
    if not ent.get("referee"):
        officials = info.get("officials") or []
        if officials:
            ent["referee"] = (officials[0] or {}).get("displayName")


def detail_skeleton(ch, ca, status="FINISHED"):
    return {
        "status": status, "fd": False, "venue": None, "attendance": None,
        "referee": None, "goals": [], "bookings": [], "substitutions": [], "penalties": [],
        "home": {"code": ch, "formation": None, "coach": None,
                 "lineup": [], "bench": [], "stats": {}},
        "away": {"code": ca, "formation": None, "coach": None,
                 "lineup": [], "bench": [], "stats": {}},
    }


def enrich_details_espn(cache, matches_resolved, index, emap=None):
    """Free, keyless second source: fill stats/lineups football-data doesn't provide."""
    live_statuses = ("IN_PLAY", "PAUSED")
    todo = [(m, ch, ca) for m, ch, ca in matches_resolved
            if ch and ca and m.get("id")
            and (m["status"] in live_statuses                         # live: re-fetch every run
                 or (m["status"] == "FINISHED"                        # finished: once
                     and not cache.get(str(m["id"]), {}).get("espn")))]
    if not todo:
        return
    if emap is None:
        emap = espn_event_map({m["utcDate"][:10] for m, _, _ in todo}, index)
    fetched = 0
    for m, ch, ca in todo:
        if fetched >= ESPN_SUMMARY_CAP:
            print(f"  ESPN summary cap reached; {len(todo) - fetched} left for next run")
            break
        eid = emap.get((m["utcDate"][:10], frozenset((ch, ca))))
        if not eid:
            continue
        try:
            if fetched:
                time.sleep(0.5)
            summary = espn_get(f"{ESPN_SUMMARY}?event={eid}")
            fetched += 1
        except Exception as e:
            print(f"  ESPN summary {eid} failed ({e}); skipping")
            continue
        ent = cache.setdefault(str(m["id"]), detail_skeleton(ch, ca, m["status"]))
        merge_espn_summary(ent, summary, index)
        if m["status"] == "FINISHED":
            ent["espn"] = True   # mark done; live matches re-merge next cycle for fresh stats
    print(f"  ESPN enrichment: {fetched} match summaries merged")


# ------------------------------------------- ESPN as full match source (no key)

def espn_stage(slug):
    s = (slug or "").lower()
    if "group" in s:
        return "GROUP_STAGE"
    if "32" in s:
        return "LAST_32"
    if "16" in s:
        return "LAST_16"
    if "quarter" in s:
        return "QUARTER_FINALS"
    if "semi" in s:
        return "SEMI_FINALS"
    if "third" in s:
        return "THIRD_PLACE"
    if "final" in s:
        return "FINAL"
    return s.upper().replace("-", "_") or "GROUP_STAGE"


def fetch_espn_groups(index):
    """{team code: 'GROUP_A'} from the ESPN standings endpoint (free, keyless)."""
    try:
        data = espn_get(f"{ESPN_STANDINGS}?season=2026")
    except Exception as e:
        print(f"  ESPN standings fetch failed ({e})")
        return {}
    out = {}
    for child in data.get("children", []):
        gname = (child.get("name") or "").upper().replace(" ", "_")
        for entry in (child.get("standings") or {}).get("entries", []):
            code = resolve_team(index, entry.get("team"))
            if code and gname:
                out[code] = gname
    print(f"  ESPN standings: group letters for {len(out)} teams")
    return out


def _espn_minute(clock):
    """\"45'+7'\" -> (45, 7); \"23'\" -> (23, None)."""
    parts = ((clock or {}).get("displayValue") or "").replace("'", " ").split("+")
    try:
        minute = int(parts[0].strip())
    except (ValueError, IndexError):
        return None, None
    injury = None
    if len(parts) > 1:
        try:
            injury = int(parts[1].strip())
        except ValueError:
            pass
    return minute, injury


def espn_key_events(comp, id_to_code):
    """Goals / cards / shootout kicks from a scoreboard competition's details."""
    goals, bookings, penalties = [], [], []
    for det in comp.get("details") or []:
        code = id_to_code.get((det.get("team") or {}).get("id"))
        ath = det.get("athletesInvolved") or []
        player = ath[0].get("displayName", "?") if ath else "?"
        minute, injury = _espn_minute(det.get("clock"))
        text = ((det.get("type") or {}).get("text") or "").lower()
        if det.get("shootout"):
            penalties.append({"team": code, "player": player, "scored": "scored" in text})
        elif det.get("scoringPlay"):
            goals.append({
                "minute": minute, "injury": injury, "team": code,
                "scorer": player,
                "assist": ath[1].get("displayName") if len(ath) > 1 else None,
                "type": ("OWN" if det.get("ownGoal")
                         else "PENALTY" if det.get("penaltyKick") else "REGULAR"),
            })
        elif det.get("redCard") or det.get("yellowCard"):
            bookings.append({"minute": minute, "team": code, "player": player,
                             "card": "RED" if det.get("redCard") else "YELLOW"})
    return goals, bookings, penalties


def fetch_espn_matches(index):
    """The whole tournament — schedule, live scores, key events, odds — from
    ESPN's keyless API, mapped into football-data's match shape so the rest of
    the pipeline doesn't care which source fed it.

    Returns (matches, info) where info[match_id] carries venue/events/odds
    for the details cache, plus an event map for the summary enrichment.
    """
    groups_of = fetch_espn_groups(index)
    matches, info, emap = [], {}, {}
    cur = WC_START
    while cur <= WC_END:
        end = min(cur + timedelta(days=6), WC_END)
        try:
            data = espn_get(f"{ESPN_SCOREBOARD}?dates={cur:%Y%m%d}-{end:%Y%m%d}")
        except Exception as e:
            print(f"  ESPN scoreboard fetch failed ({e})")
            cur = end + timedelta(days=1)
            continue
        for e in data.get("events", []):
            c = (e.get("competitions") or [{}])[0]
            comps = c.get("competitors") or []
            home = next((t for t in comps if t.get("homeAway") == "home"), None)
            away = next((t for t in comps if t.get("homeAway") == "away"), None)
            state = (e.get("status") or {}).get("type") or {}
            if not home or not away or state.get("name") in ("STATUS_POSTPONED",
                                                             "STATUS_CANCELED"):
                continue
            status = ("FINISHED" if state.get("state") == "post" and state.get("completed")
                      else "IN_PLAY" if state.get("state") == "in" else "TIMED")
            stage = espn_stage((e.get("season") or {}).get("slug"))
            hc = resolve_team(index, home.get("team"))
            ac = resolve_team(index, away.get("team"))
            date = e.get("date") or ""
            if len(date) == 17:                      # "2026-06-11T19:00Z"
                date = date[:16] + ":00Z"

            score = {}
            if status != "TIMED":
                try:
                    hg, ag = int(home.get("score") or 0), int(away.get("score") or 0)
                except (TypeError, ValueError):
                    hg = ag = 0
                score = {"duration": "REGULAR", "fullTime": {"home": hg, "away": ag}}
                hs, as_ = home.get("shootoutScore"), away.get("shootoutScore")
                if hs is not None and as_ is not None:
                    score.update({
                        "duration": "PENALTY_SHOOTOUT",
                        "regularTime": {"home": hg, "away": ag},
                        "extraTime": {"home": 0, "away": 0},
                        "penalties": {"home": int(hs), "away": int(as_)},
                    })
                    if status == "FINISHED":
                        score["winner"] = "HOME_TEAM" if int(hs) > int(as_) else "AWAY_TEAM"
                elif status == "FINISHED":
                    score["winner"] = ("HOME_TEAM" if hg > ag
                                       else "AWAY_TEAM" if ag > hg else "DRAW")

            mid = int(e["id"])
            group = groups_of.get(hc) or groups_of.get(ac) if stage == "GROUP_STAGE" else None
            matches.append({
                "id": mid, "utcDate": date, "status": status, "stage": stage,
                "group": group,
                "homeTeam": {"name": (home.get("team") or {}).get("displayName")},
                "awayTeam": {"name": (away.get("team") or {}).get("displayName")},
                "score": score,
            })
            id_to_code = {(t.get("team") or {}).get("id"): resolve_team(index, t.get("team"))
                          for t in comps}
            goals, bookings, pens = espn_key_events(c, id_to_code)
            info[mid] = {
                "venue": (c.get("venue") or {}).get("fullName"),
                "attendance": c.get("attendance") or None,
                "odds": parse_espn_odds(c),
                "clock": (e.get("status") or {}).get("displayClock"),
                "clock_sec": (e.get("status") or {}).get("clock"),   # exact elapsed seconds
                "status_detail": state.get("shortDetail") or state.get("detail"),
                "goals": goals, "bookings": bookings, "penalties": pens,
            }
            if hc and ac:
                emap[date[:10], frozenset((hc, ac))] = e.get("id")
        cur = end + timedelta(days=1)
    print(f"  ESPN source: {len(matches)} fixtures "
          f"({sum(1 for m in matches if m['status'] == 'FINISHED')} finished)")
    return matches, info, emap


def merge_espn_match_info(cache, matches_resolved, info):
    """Fold venue/odds/key events from the scoreboard into the details cache.

    football-data remains authoritative where it has fetched a match (fd flag);
    odds are kept regardless because no other source provides them."""
    for m, ch, ca in matches_resolved:
        mi = info.get(m.get("id"))
        if not mi or not ch or not ca:
            continue
        has_content = (mi.get("odds") or mi.get("goals") or mi.get("bookings")
                       or m["status"] in ("FINISHED", "IN_PLAY", "PAUSED"))
        if not has_content:
            continue
        ent = cache.setdefault(str(m["id"]), detail_skeleton(ch, ca, m["status"]))
        if mi.get("odds") and not ent.get("odds"):
            ent["odds"] = mi["odds"]
        ent["venue"] = ent.get("venue") or mi.get("venue")
        ent["attendance"] = ent.get("attendance") or mi.get("attendance")
        if not ent.get("fd"):
            ent["status"] = m["status"]
            for key in ("goals", "bookings", "penalties"):
                if mi.get(key):
                    ent[key] = mi[key]


def scorers_from_details(cache, teams_by_code, owner):
    """Golden Boot table built from cached goal events (keyless fallback)."""
    tally = {}
    for ent in cache.values():
        for g in ent.get("goals") or []:
            if g.get("type") == "OWN":
                continue
            if g.get("scorer") and g["scorer"] != "?":
                t = tally.setdefault((g["scorer"], g.get("team")),
                                     {"player": g["scorer"], "team": g.get("team"),
                                      "goals": 0, "assists": 0})
                t["goals"] += 1
            if g.get("assist"):
                t = tally.setdefault((g["assist"], g.get("team")),
                                     {"player": g["assist"], "team": g.get("team"),
                                      "goals": 0, "assists": 0})
                t["assists"] += 1
    out = sorted(tally.values(), key=lambda s: (-s["goals"], -s["assists"], s["player"]))[:15]
    for s in out:
        team = teams_by_code.get(s["team"])
        s["flag"] = team["flag"] if team else ""
        s["owner"] = owner.get(s["team"])
    return out


# ---------------------------------------------------------------- match detail

def extract_side(api_team, index):
    return {
        "code": resolve_team(index, api_team),
        "formation": api_team.get("formation"),
        "coach": (api_team.get("coach") or {}).get("name"),
        "lineup": [{"name": p.get("name"), "position": p.get("position"),
                    "shirt": p.get("shirtNumber")} for p in api_team.get("lineup") or []],
        "bench": [{"name": p.get("name"), "position": p.get("position"),
                   "shirt": p.get("shirtNumber")} for p in api_team.get("bench") or []],
        "stats": api_team.get("statistics") or {},
    }


def extract_detail(d, index):
    referee = next((r.get("name") for r in d.get("referees") or []
                    if r.get("role") in (None, "REFEREE")), None)
    return {
        "status": d.get("status"),
        "venue": d.get("venue"),
        "attendance": d.get("attendance"),
        "referee": referee,
        "goals": [{
            "minute": g.get("minute"), "injury": g.get("injuryTime"),
            "team": resolve_team(index, g.get("team")),
            "scorer": (g.get("scorer") or {}).get("name", "?"),
            "assist": (g.get("assist") or {}).get("name"),
            "type": g.get("type"),
        } for g in d.get("goals") or []],
        "bookings": [{
            "minute": b.get("minute"), "team": resolve_team(index, b.get("team")),
            "player": (b.get("player") or {}).get("name", "?"),
            "card": b.get("card"),
        } for b in d.get("bookings") or []],
        "substitutions": [{
            "minute": s.get("minute"), "team": resolve_team(index, s.get("team")),
            "out": (s.get("playerOut") or {}).get("name", "?"),
            "in": (s.get("playerIn") or {}).get("name", "?"),
        } for s in d.get("substitutions") or []],
        "penalties": [{
            "team": resolve_team(index, p.get("team")),
            "player": (p.get("player") or {}).get("name", "?"),
            "scored": p.get("scored"),
        } for p in d.get("penalties") or []],
        "home": extract_side(d.get("homeTeam") or {}, index),
        "away": extract_side(d.get("awayTeam") or {}, index),
    }


def update_details(token, matches_resolved, index):
    """Fetch per-match detail for recent matches, throttled, into docs/details.json."""
    cache_path = ROOT / "docs/details.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    def needs_fetch(m):
        c = cache.get(str(m["id"]), {})
        return not (c.get("fd") and c.get("status") == "FINISHED")

    candidates = [
        m for m, ch, ca in matches_resolved
        if ch and ca and m.get("id")
        and m["status"] in ("FINISHED", "IN_PLAY", "PAUSED")
        and needs_fetch(m)
    ]
    candidates.sort(key=lambda m: m["utcDate"], reverse=True)
    todo = candidates[:DETAIL_FETCH_CAP]
    if len(candidates) > DETAIL_FETCH_CAP:
        print(f"  detail backlog: {len(candidates)} matches, fetching newest "
              f"{DETAIL_FETCH_CAP} this run (the rest next run)")

    for i, m in enumerate(todo):
        if i:
            time.sleep(DETAIL_FETCH_PAUSE)
        url = f"{API_BASE}/matches/{m['id']}"
        try:
            detail = fetch_json(url, token)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("  rate limited; waiting 65s...")
                time.sleep(65)
                try:
                    detail = fetch_json(url, token)
                except Exception as e2:
                    print(f"  giving up on details this run ({e2})")
                    break
            else:
                print(f"  detail fetch {m['id']} failed ({e}); skipping")
                continue
        except Exception as e:
            print(f"  detail fetch {m['id']} failed ({e}); skipping")
            continue
        new = extract_detail(detail, index)
        new["fd"] = True
        old = cache.get(str(m["id"]))
        if old and old.get("odds"):
            new["odds"] = old["odds"]   # odds only ever come from ESPN; keep them
        if old and old.get("espn"):
            # keep ESPN-sourced stats/lineups that football-data doesn't have
            for side_key in ("home", "away"):
                ns, os_ = new[side_key], old.get(side_key) or {}
                for k, v in (os_.get("stats") or {}).items():
                    ns.setdefault("stats", {}).setdefault(k, v)
                if not ns.get("lineup"):
                    ns["lineup"], ns["bench"] = os_.get("lineup") or [], os_.get("bench") or []
                if not ns.get("formation"):
                    ns["formation"] = os_.get("formation")
                if not ns.get("coach"):
                    ns["coach"] = os_.get("coach")
            for k in ("venue", "attendance", "referee"):
                if not new.get(k):
                    new[k] = old.get(k)
            new["espn"] = True
        cache[str(m["id"])] = new

    print(f"  match details cached: {len(cache)} matches ({len(todo)} fetched this run)")
    return cache


# ---------------------------------------------------------------- group tables

def compute_groups(matches_resolved, teams_by_code, owner):
    """Build group tables locally from the fixture list (no extra API calls).

    In-play matches count at their CURRENT score — the table is always
    'as it stands'; it self-corrects at full-time on the next run."""
    members = defaultdict(set)
    rows = {}
    for m, ch, ca in matches_resolved:
        if m.get("stage") != "GROUP_STAGE" or not m.get("group"):
            continue
        gname = m["group"].replace("_", " ").title()
        for code in (ch, ca):
            if code:
                members[gname].add(code)

    for gname, codes in members.items():
        for code in codes:
            rows[code] = {"group": gname, "code": code, "p": 0, "w": 0, "d": 0,
                          "l": 0, "gf": 0, "ga": 0, "pts": 0, "live": False}

    for m, ch, ca in matches_resolved:
        if m.get("stage") != "GROUP_STAGE" or not ch or not ca \
                or m["status"] not in ("FINISHED", "IN_PLAY", "PAUSED"):
            continue
        in_play = m["status"] != "FINISHED"
        hg, ag = match_goals(m["score"])
        for code, gf, ga in ((ch, hg, ag), (ca, ag, hg)):
            if code not in rows:
                continue
            r = rows[code]
            r["p"] += 1
            r["gf"] += gf
            r["ga"] += ga
            if in_play:
                r["live"] = True
            if gf > ga:
                r["w"] += 1
                r["pts"] += 3
            elif gf == ga:
                r["d"] += 1
                r["pts"] += 1
            else:
                r["l"] += 1

    groups = []
    for gname in sorted(members):
        table = sorted((rows[c] for c in members[gname]),
                       key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"],
                                      teams_by_code[r["code"]]["name"]))
        groups.append({"name": gname, "rows": [{
            **r, "gd": r["gf"] - r["ga"],
            "name": teams_by_code[r["code"]]["name"],
            "flag": teams_by_code[r["code"]]["flag"],
            "tier": teams_by_code[r["code"]]["tier"],
            "owner": owner.get(r["code"]),
        } for r in table]})
    return groups


# ---------------------------------------------------------------- demo fixtures

def demo_matches():
    """A fake first two matchdays so you can preview how scoring plays out."""
    def m(mid, date, group, home, away, hg, ag, winner, duration="REGULAR"):
        return {
            "id": mid,
            "utcDate": f"{date}T18:00:00Z",
            "status": "FINISHED",
            "stage": "GROUP_STAGE",
            "group": group,
            "homeTeam": {"name": home},
            "awayTeam": {"name": away},
            "score": {"winner": winner, "duration": duration,
                      "fullTime": {"home": hg, "away": ag}},
        }
    return [
        m(101, "2026-06-11", "GROUP_A", "Mexico", "South Africa", 2, 0, "HOME_TEAM"),
        m(102, "2026-06-11", "GROUP_B", "Haiti", "Belgium", 1, 1, "DRAW"),
        m(103, "2026-06-12", "GROUP_C", "New Zealand", "Argentina", 2, 1, "HOME_TEAM"),
        m(104, "2026-06-12", "GROUP_D", "USA", "Paraguay", 3, 0, "HOME_TEAM"),
        m(105, "2026-06-12", "GROUP_E", "Japan", "Germany", 2, 1, "HOME_TEAM"),
        m(106, "2026-06-12", "GROUP_F", "France", "Ghana", 4, 0, "HOME_TEAM"),
        {"id": 107, "utcDate": "2026-06-13T16:00:00Z", "status": "TIMED",
         "stage": "GROUP_STAGE", "group": "GROUP_G",
         "homeTeam": {"name": "England"}, "awayTeam": {"name": "Croatia"}, "score": {}},
        {"id": 108, "utcDate": "2026-06-13T19:00:00Z", "status": "TIMED",
         "stage": "GROUP_STAGE", "group": "GROUP_H",
         "homeTeam": {"name": "Brazil"}, "awayTeam": {"name": "Morocco"}, "score": {}},
    ]


DEMO_EXTRAS = {
    ("2026-06-13", frozenset(("ENG", "CRO"))): {
        "odds": {"home": 2.1, "draw": 3.3, "away": 3.6, "over_under": 2.5,
                 "provider": "DraftKings"},
        "form": {"ENG": "WWWDW", "CRO": "WDWLW"},
    },
    ("2026-06-13", frozenset(("BRA", "MAR"))): {
        "odds": {"home": 1.85, "draw": 3.5, "away": 4.2, "over_under": 2.5,
                 "provider": "DraftKings"},
        "form": {"BRA": "WWDWW", "MAR": "WWWWD"},
    },
}


DEMO_SURNAMES = ["Smith", "García", "Müller", "Silva", "Rossi", "Dubois", "Yamada", "Kim",
                 "Diallo", "Okafor", "Novak", "Jansen", "Costa", "Petrov", "Hansen", "Moreau",
                 "Ricci", "Vargas", "Tanaka", "Mensah", "Keita", "Ali", "Hussein", "Park",
                 "Berg", "Olsen", "Castro", "Lopez", "Schmidt", "Weber", "Fischer", "Sato",
                 "Suzuki", "Traoré", "Cissé", "Ndiaye", "Fernandes", "Pereira", "Santos", "Ramírez"]


def _demo_names(code, count, salt=0):
    base = sum(ord(c) for c in code) + salt
    return [f"{chr(65 + (base + i) % 26)}. {DEMO_SURNAMES[(base + i * 3) % len(DEMO_SURNAMES)]}"
            for i in range(count)]


def _demo_side(code, possession):
    positions = ["Goalkeeper", "Right-Back", "Centre-Back", "Centre-Back", "Left-Back",
                 "Defensive Midfield", "Central Midfield", "Central Midfield",
                 "Right Winger", "Centre-Forward", "Left Winger"]
    names = _demo_names(code, 11)
    bench = _demo_names(code, 5, salt=17)
    return {
        "code": code,
        "formation": "4-3-3",
        "coach": _demo_names(code, 1, salt=29)[0],
        "lineup": [{"name": n, "position": p, "shirt": i + 1}
                   for i, (n, p) in enumerate(zip(names, positions))],
        "bench": [{"name": n, "position": None, "shirt": 12 + i} for i, n in enumerate(bench)],
        "stats": {
            "ball_possession": possession,
            "shots": 6 + possession // 6,
            "shots_on_goal": 2 + possession // 15,
            "corner_kicks": 2 + possession // 12,
            "passes": 280 + possession * 5,
            "pass_accuracy": 68 + possession // 4,
            "crosses": 8 + possession // 10,
            "long_balls": 70 - possession // 3,
            "fouls": 16 - possession // 8,
            "offsides": 1 + possession // 30,
            "saves": 3,
            "yellow_cards": 1 if possession >= 50 else 2,
            "red_cards": 0,
        },
    }


def demo_details(matches_resolved, teams_by_code):
    details = {}
    for m, ch, ca in matches_resolved:
        hg, ag = match_goals(m["score"])
        # favourites (lower tier number) dominate the ball
        th, ta = teams_by_code[ch]["tier"], teams_by_code[ca]["tier"]
        poss_home = 50 + (ta - th) * 12
        home, away = _demo_side(ch, poss_home), _demo_side(ca, 100 - poss_home)
        goals, bookings, subs = [], [], []
        for side, n in ((home, hg), (away, ag)):
            base = sum(ord(c) for c in side["code"])
            for i in range(n):
                goals.append({"minute": 9 + base % 7 + i * 23, "injury": None,
                              "team": side["code"],
                              "scorer": side["lineup"][9 - (i % 3)]["name"],
                              "assist": side["lineup"][6 + (i % 3)]["name"],
                              "type": "PENALTY" if (base + i) % 5 == 0 else "REGULAR"})
            bookings.append({"minute": 30 + base % 25, "team": side["code"],
                             "player": side["lineup"][5]["name"], "card": "YELLOW"})
            for j, mins in enumerate((61, 74, 85)):
                subs.append({"minute": mins, "team": side["code"],
                             "out": side["lineup"][8 - j]["name"],
                             "in": side["bench"][j]["name"]})
        details[str(m["id"])] = {
            "status": "FINISHED", "venue": "Estadio Azteca, Mexico City",
            "attendance": 87523, "referee": "F. Rapallini",
            "goals": sorted(goals, key=lambda g: g["minute"]),
            "bookings": bookings, "substitutions": sorted(subs, key=lambda s: s["minute"]),
            "penalties": [], "home": home, "away": away,
        }
    return details


DEMO_SCORERS = [
    {"player": "K. Mbappé", "team": "FRA", "goals": 2, "assists": 1},
    {"player": "C. Wood", "team": "NZL", "goals": 2, "assists": 0},
    {"player": "T. Kubo", "team": "JPN", "goals": 1, "assists": 1},
    {"player": "C. Pulisic", "team": "USA", "goals": 1, "assists": 1},
    {"player": "H. Lozano", "team": "MEX", "goals": 1, "assists": 0},
    {"player": "D. Duranville", "team": "HAI", "goals": 1, "assists": 0},
]


# ---------------------------------------------------------------- scoring core

def match_goals(score):
    """Goals over regulation + extra time (penalty shootout goals don't count)."""
    if score.get("duration") == "PENALTY_SHOOTOUT":
        reg = score.get("regularTime")
        extra = score.get("extraTime")
        if reg and extra:
            return (reg["home"] + extra["home"], reg["away"] + extra["away"])
    ft = score.get("fullTime", {})
    return (ft.get("home") or 0, ft.get("away") or 0)


ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


def add_group_position_events(groups, matches_resolved, cfg, events):
    """Score group-stage positions live: 1st 5, 2nd 3, 3rd 1, 4th 0.

    Positions are provisional while the group is in play and final once all
    6 group matches have finished. Events are dated by the team's most recent
    group match so the leaderboard's 'Latest' delta and movement arrows work.
    """
    last_date = {}                       # code -> date of latest counted group match
    finished_per_group = defaultdict(int)
    for m, ch, ca in matches_resolved:
        if m.get("stage") != "GROUP_STAGE" \
                or m["status"] not in ("FINISHED", "IN_PLAY", "PAUSED"):
            continue
        if m["status"] == "FINISHED" and m.get("group"):
            finished_per_group[m["group"].replace("_", " ").title()] += 1
        for code in (ch, ca):
            if code:
                last_date[code] = max(last_date.get(code, ""), m["utcDate"][:10])

    for g in groups:
        done = finished_per_group.get(g["name"], 0) >= 6  # 4 teams = 6 matches
        for pos, row in enumerate(g["rows"], 1):
            if row["p"] == 0:        # no points until you've kicked a ball
                continue
            pts = cfg["group_position"].get(str(pos), 0)
            if pts <= 0:
                continue
            desc = f"{ORDINALS[pos]} in {g['name']}" + ("" if done else " (live)")
            events[row["code"]].append({
                "date": last_date.get(row["code"], ""), "points": pts,
                "desc": desc, "kind": "group",
            })


def add_knockout_events(matches_resolved, teams_by_code, cfg, events):
    """Award points for winning each knockout tie (shootout wins count)."""
    for m, ch, ca in matches_resolved:
        stage = m.get("stage")
        pts = cfg["knockout_win"].get(stage)
        if not pts or m["status"] != "FINISHED" or not ch or not ca:
            continue
        winner = m["score"].get("winner")
        win_code = ch if winner == "HOME_TEAM" else ca if winner == "AWAY_TEAM" else None
        if not win_code:
            continue
        pens = m["score"].get("duration") == "PENALTY_SHOOTOUT"
        if stage == "FINAL":
            desc = "WORLD CHAMPIONS" + (" (on penalties)" if pens else "")
            teams_by_code[win_code]["_champion"] = True
        else:
            desc = f"Won {STAGE_LABELS[stage]} tie" + (" (on penalties)" if pens else "")
        events[win_code].append({
            "date": m["utcDate"][:10], "points": pts, "desc": desc, "kind": "knockout",
        })


def compute_status(matches_resolved, teams_by_code):
    """Mark each team alive/eliminated/champion as far as we can tell."""
    status = {c: "alive" for c in teams_by_code}
    r32_exists = any(m["stage"] == "LAST_32" for m, _, _ in matches_resolved)
    in_r32 = {c for m, ch, ca in matches_resolved if m["stage"] == "LAST_32" for c in (ch, ca) if c}
    group_done = all(m["status"] == "FINISHED" for m, _, _ in matches_resolved
                     if m["stage"] == "GROUP_STAGE") if r32_exists else False

    if r32_exists and group_done:
        for c in status:
            if c not in in_r32:
                status[c] = "out"

    for m, ch, ca in matches_resolved:
        if m["stage"] in ("LAST_32", "LAST_16", "QUARTER_FINALS", "THIRD_PLACE", "FINAL") \
                and m["status"] == "FINISHED" and ch and ca:
            winner = m["score"].get("winner")
            loser = ca if winner == "HOME_TEAM" else ch if winner == "AWAY_TEAM" else None
            if loser:
                status[loser] = "out"

    for c, t in teams_by_code.items():
        if t.get("_champion"):
            status[c] = "champion"
    return status


def ranked(totals_by_player):
    """[(rank, name, total)] with standard competition ranking for ties."""
    rows = sorted(totals_by_player.items(), key=lambda kv: (-kv[1], kv[0]))
    out, prev_total, prev_rank = [], None, 0
    for i, (name, total) in enumerate(rows, 1):
        rank = prev_rank if total == prev_total else i
        out.append((rank, name, total))
        prev_total, prev_rank = total, rank
    return out


def main():
    mode = "live"
    if "--offline" in sys.argv:
        mode = "offline"
    elif "--demo" in sys.argv:
        mode = "demo"

    teams = load_json("data/teams.json")["teams"]
    players = load_json("data/players.json")["players"]
    cfg = load_json("data/scoring.json")
    teams_by_code = {t["code"]: t for t in teams}
    index = build_team_index(teams)
    owner = {}
    for p in players:
        for code in p.get("teams", []):
            owner[code] = p["name"]

    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    espn_info, espn_emap = {}, None
    if mode == "live":
        if token:
            matches = fetch_matches(token)
        else:
            print("No FOOTBALL_DATA_TOKEN — using ESPN's keyless API as the live source.")
            matches, espn_info, espn_emap = fetch_espn_matches(index)
    elif mode == "demo":
        matches = demo_matches()
    else:
        matches = []

    matches_resolved = [
        (m, resolve_team(index, m.get("homeTeam")), resolve_team(index, m.get("awayTeam")))
        for m in matches
    ]

    events = defaultdict(list)
    results = []

    for m, ch, ca in matches_resolved:
        if m["status"] != "FINISHED" or not ch or not ca:
            continue
        hg, ag = match_goals(m["score"])
        pens = m["score"].get("duration") == "PENALTY_SHOOTOUT"
        note = ""
        if pens:
            p = m["score"].get("penalties")
            note = f" ({p['home']}-{p['away']} pens)" if p else " (pens)"
        # Direct match points only exist for knockout ties; group games move
        # the group table instead (scored as positions, see scoring.json).
        kw = cfg["knockout_win"].get(m["stage"])
        winner = m["score"].get("winner")
        hpts = apts = None
        if kw:
            hpts = kw if winner == "HOME_TEAM" else 0
            apts = kw if winner == "AWAY_TEAM" else 0
        results.append({
            "id": m.get("id"),
            "date": m["utcDate"][:10],
            "utc": m["utcDate"],
            "stage": STAGE_LABELS.get(m["stage"], m["stage"]),
            "group": (m.get("group") or "").replace("_", " ").title() or None,
            "note": note,
            "home": {"code": ch, "name": teams_by_code[ch]["name"], "flag": teams_by_code[ch]["flag"],
                     "tier": teams_by_code[ch]["tier"], "goals": hg, "points": hpts},
            "away": {"code": ca, "name": teams_by_code[ca]["name"], "flag": teams_by_code[ca]["flag"],
                     "tier": teams_by_code[ca]["tier"], "goals": ag, "points": apts},
        })

    groups = compute_groups(matches_resolved, teams_by_code, owner)
    add_group_position_events(groups, matches_resolved, cfg, events)
    add_knockout_events(matches_resolved, teams_by_code, cfg, events)
    status = compute_status(matches_resolved, teams_by_code)

    # Match details, top scorers, odds
    if mode == "live":
        if token:
            cache = update_details(token, matches_resolved, index)
        else:
            cache_path = ROOT / "docs/details.json"
            cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        # drop cached matches that aren't in the real fixture list (demo leftovers,
        # changed ids) — but never on a partial fetch, that would wipe good data
        valid_ids = {str(m["id"]) for m, _, _ in matches_resolved if m.get("id")}
        if len(valid_ids) > 50:
            stale = set(cache) - valid_ids
            if stale:
                cache = {k: v for k, v in cache.items() if k in valid_ids}
                print(f"  purged {len(stale)} stale cached match entries")
        merge_espn_match_info(cache, matches_resolved, espn_info)
        enrich_details_espn(cache, matches_resolved, index, emap=espn_emap)
        extras = fetch_espn_extras(index)
        # remember pre-match odds so they're still shown after full-time
        for m, ch, ca in matches_resolved:
            if not (ch and ca and m.get("id")):
                continue
            ex = extras.get((m["utcDate"][:10], frozenset((ch, ca))), {})
            if ex.get("odds") and not cache.get(str(m["id"]), {}).get("odds"):
                ent = cache.setdefault(str(m["id"]), detail_skeleton(ch, ca, m["status"]))
                ent["odds"] = ex["odds"]
        write_json(ROOT / "docs/details.json", cache)
        scorers = (fetch_scorers(token, index, teams_by_code, owner) if token
                   else scorers_from_details(cache, teams_by_code, owner))
    elif mode == "demo":
        finished_demo = [(m, ch, ca) for m, ch, ca in matches_resolved if m["status"] == "FINISHED"]
        cache = demo_details(finished_demo, teams_by_code)
        for i, ent in enumerate(cache.values()):
            ent["odds"] = {"home": 1.5 + (i % 4) * 0.45, "draw": 3.4, "away": 2.2 + (i % 5),
                           "over_under": 2.5, "provider": "DraftKings"}
        write_json(ROOT / "docs/details.json", cache)
        scorers = [{**s, "flag": teams_by_code[s["team"]]["flag"],
                    "owner": owner.get(s["team"])} for s in DEMO_SCORERS]
        extras = DEMO_EXTRAS
    else:
        cache = {}
        write_json(ROOT / "docs/details.json", {})
        scorers = []
        extras = {}

    # Pre-match odds belong on every match card, finished or not
    for r in results:
        r["odds"] = cache.get(str(r["id"]), {}).get("odds")

    # Per-team totals and W/D/L records
    team_out = {}
    for code, t in teams_by_code.items():
        evs = sorted(events[code], key=lambda e: e["date"])
        total = sum(e["points"] for e in evs)
        played = [r for r in results if code in (r["home"]["code"], r["away"]["code"])]
        won = drawn = lost = gf = ga = 0
        for r in played:
            us, them = (r["home"], r["away"]) if r["home"]["code"] == code else (r["away"], r["home"])
            gf, ga = gf + us["goals"], ga + them["goals"]
            if us["goals"] > them["goals"]:
                won += 1
            elif us["goals"] < them["goals"]:
                lost += 1
            else:
                drawn += 1
        team_out[code] = {
            "code": code, "name": t["name"], "flag": t["flag"], "tier": t["tier"],
            "fifa_rank": t["fifa_rank"],
            "owner": owner.get(code), "status": status[code],
            "played": len(played), "won": won, "drawn": drawn, "lost": lost,
            "gf": gf, "ga": ga, "total": total,
            "events": [{"date": e["date"], "desc": e["desc"], "points": e["points"]}
                       for e in sorted(evs, key=lambda e: e["date"], reverse=True)],
        }

    # Fair Play table — most cards = worst (yellow 1, second yellow 3, red 4)
    fairplay = {}
    for r in results:
        ent = cache.get(str(r["id"]), {})
        for b in ent.get("bookings") or []:
            code = b.get("team")
            if code not in teams_by_code:
                continue
            fp = fairplay.setdefault(code, {"yellow": 0, "red": 0, "pts": 0})
            card = (b.get("card") or "YELLOW").upper()
            if card == "YELLOW_RED":
                fp["red"] += 1
                fp["pts"] += 3
            elif card == "RED":
                fp["red"] += 1
                fp["pts"] += 4
            else:
                fp["yellow"] += 1
                fp["pts"] += 1
    fairplay_rows = sorted(
        ({"code": c, "name": teams_by_code[c]["name"], "flag": teams_by_code[c]["flag"],
          "owner": owner.get(c), **v} for c, v in fairplay.items()),
        key=lambda x: (-x["pts"], -x["red"], -x["yellow"], x["name"]))

    # Player totals, plus "latest matchday" delta and movement
    finished_dates = sorted({r["date"] for r in results})
    latest_day = finished_dates[-1] if finished_dates else None

    def player_total(p, before=None):
        tot = 0
        for code in p.get("teams", []):
            for e in events[code]:
                if before is None or e["date"] < before:
                    tot += e["points"]
        return tot

    totals_now = {p["name"]: player_total(p) for p in players}
    totals_before = {p["name"]: player_total(p, before=latest_day) for p in players} \
        if latest_day else totals_now

    rank_now = {name: r for r, name, _ in ranked(totals_now)}
    rank_before = {name: r for r, name, _ in ranked(totals_before)}

    players_out = []
    for p in players:
        name = p["name"]
        players_out.append({
            "name": name,
            "teams": p.get("teams", []),
            "total": totals_now[name],
            "today": round(totals_now[name] - totals_before[name], 1),
            "rank": rank_now[name],
            "movement": rank_before[name] - rank_now[name],
        })
    players_out.sort(key=lambda p: (p["rank"], p["name"]))

    # In-play matches get their own hero section at the top of the page
    live = []
    for m, ch, ca in matches_resolved:
        if m["status"] not in ("IN_PLAY", "PAUSED") or not ch or not ca:
            continue
        hg, ag = match_goals(m["score"])
        mi = espn_info.get(m.get("id"), {})
        ent = cache.get(str(m.get("id")), {})
        live.append({
            "id": m.get("id"),
            "utc": m["utcDate"],
            "stage": STAGE_LABELS.get(m["stage"], m["stage"]),
            "group": (m.get("group") or "").replace("_", " ").title() or None,
            "clock": mi.get("clock"),
            "clock_sec": mi.get("clock_sec"),
            "status_detail": mi.get("status_detail") or ("Half-time" if m["status"] == "PAUSED" else "Live"),
            "venue": mi.get("venue") or ent.get("venue"),
            "odds": ent.get("odds"),
            "home": {"code": ch, "name": teams_by_code[ch]["name"], "flag": teams_by_code[ch]["flag"],
                     "owner": owner.get(ch), "goals": hg},
            "away": {"code": ca, "name": teams_by_code[ca]["name"], "flag": teams_by_code[ca]["flag"],
                     "owner": owner.get(ca), "goals": ag},
        })
    live.sort(key=lambda u: u["utc"], reverse=True)

    upcoming = []
    for m, ch, ca in matches_resolved:
        if m["status"] in ("SCHEDULED", "TIMED") and ch and ca:
            extra = extras.get((m["utcDate"][:10], frozenset((ch, ca))), {})
            form = extra.get("form") or {}
            upcoming.append({
                "id": m.get("id"),
                "utc": m["utcDate"],
                "stage": STAGE_LABELS.get(m["stage"], m["stage"]),
                "group": (m.get("group") or "").replace("_", " ").title() or None,
                "odds": extra.get("odds") or cache.get(str(m.get("id")), {}).get("odds"),
                "home": {"name": teams_by_code[ch]["name"], "flag": teams_by_code[ch]["flag"],
                         "owner": owner.get(ch), "form": form.get(ch)},
                "away": {"name": teams_by_code[ca]["name"], "flag": teams_by_code[ca]["flag"],
                         "owner": owner.get(ca), "form": form.get(ca)},
            })
    upcoming.sort(key=lambda u: u["utc"])

    # Knockout bracket — includes unresolved ties ("Group A Winner" etc.)
    bracket = []
    for m, ch, ca in matches_resolved:
        if m["stage"] not in KNOCKOUT_STAGES:
            continue

        def bside(code, raw):
            if code:
                t = teams_by_code[code]
                return {"code": code, "name": t["name"], "flag": t["flag"],
                        "owner": owner.get(code)}
            return {"code": None, "name": (raw or {}).get("name") or "TBD",
                    "flag": "", "owner": None}

        finished = m["status"] == "FINISHED"
        hg, ag = match_goals(m["score"]) if finished else (None, None)
        winner = m["score"].get("winner") if finished else None
        note = ""
        if finished and m["score"].get("duration") == "PENALTY_SHOOTOUT":
            p = m["score"].get("penalties")
            note = f"{p['home']}-{p['away']} pens" if p else "pens"
        bracket.append({
            "id": m.get("id"), "utc": m["utcDate"], "stage": m["stage"],
            "status": m["status"], "hg": hg, "ag": ag, "note": note,
            "winner": ch if winner == "HOME_TEAM" else ca if winner == "AWAY_TEAM" else None,
            "venue": espn_info.get(m.get("id"), {}).get("venue")
                     or cache.get(str(m.get("id")), {}).get("venue"),
            "home": bside(ch, m.get("homeTeam")),
            "away": bside(ca, m.get("awayTeam")),
        })
    bracket.sort(key=lambda b: b["utc"])

    news = fetch_news() if "--offline" not in sys.argv else []

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "latest_day": latest_day,
        "scoring": cfg,
        "players": players_out,
        "teams": team_out,
        "live": live,
        "results": sorted(results, key=lambda r: r["utc"], reverse=True),
        "upcoming": upcoming,
        "groups": groups,
        "bracket": bracket,
        "scorers": scorers,
        "fairplay": fairplay_rows,
        "news": news,
    }
    write_json(ROOT / "docs/data.json", out, indent=1)
    print(f"Wrote docs/data.json ({mode} mode): {len(results)} finished matches, "
          f"latest matchday {latest_day or 'n/a'}")


if __name__ == "__main__":
    main()
