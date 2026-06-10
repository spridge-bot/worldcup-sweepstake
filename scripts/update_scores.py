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
  Every point a team earns is multiplied by its tier multiplier
  (Tier 1 x1, Tier 2 x1.5, Tier 3 x2), so underdogs climb fast.
  - Win 3 / Draw 1 (losing a penalty shootout counts as a draw)
  - +1 per goal scored, +1 clean sheet
  - Upset bonus: beat a team from a higher tier: +4 per tier gap
    (draw with one: +2 per tier gap)
  - Progression: reach R32 +4, R16 +6, QF +8, SF +10, Final +12, win it all +15
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


def fetch_espn_extras(index):
    """Odds + recent form for upcoming fixtures from ESPN's public scoreboard API.

    Free, no key needed. Returns {(date, {home,away} codes): {odds, form}}.
    Fails soft — the sweepstake works fine without it.
    """
    start = datetime.now(timezone.utc)
    rng = f"{start:%Y%m%d}-{start + timedelta(days=10):%Y%m%d}"
    try:
        req = urllib.request.Request(f"{ESPN_SCOREBOARD}?dates={rng}",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
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
        odds = (c.get("odds") or [{}])[0]
        ml = odds.get("moneyline") or {}

        def closing(side):
            return american_to_decimal((((ml.get(side) or {}).get("close")) or {}).get("odds"))

        h, a = closing("home"), closing("away")
        draw_ml = (odds.get("drawOdds") or {}).get("moneyLine")
        d = american_to_decimal(draw_ml) if draw_ml is not None else None
        if h or a or d:
            entry["odds"] = {
                "home": h, "draw": d, "away": a,
                "over_under": odds.get("overUnder"),
                "provider": (odds.get("provider") or {}).get("displayName") or "DraftKings",
            }
        out[(e.get("date") or "")[:10], frozenset((hc, ac))] = entry
    found = sum(1 for v in out.values() if "odds" in v)
    print(f"  ESPN: odds for {found} of {len(out)} upcoming fixtures")
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

    candidates = [
        m for m, ch, ca in matches_resolved
        if ch and ca and m.get("id")
        and m["status"] in ("FINISHED", "IN_PLAY", "PAUSED")
        and cache.get(str(m["id"]), {}).get("status") != "FINISHED"
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
        cache[str(m["id"])] = extract_detail(detail, index)

    cache_path.write_text(json.dumps(cache, ensure_ascii=False) + "\n")
    print(f"  match details cached: {len(cache)} matches ({len(todo)} fetched this run)")


# ---------------------------------------------------------------- group tables

def compute_groups(matches_resolved, teams_by_code, owner):
    """Build group tables locally from the fixture list (no extra API calls)."""
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
                          "l": 0, "gf": 0, "ga": 0, "pts": 0}

    for m, ch, ca in matches_resolved:
        if m.get("stage") != "GROUP_STAGE" or m["status"] != "FINISHED" or not ch or not ca:
            continue
        hg, ag = match_goals(m["score"])
        for code, gf, ga in ((ch, hg, ag), (ca, ag, hg)):
            if code not in rows:
                continue
            r = rows[code]
            r["p"] += 1
            r["gf"] += gf
            r["ga"] += ga
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


def score_match(match, code_home, code_away, teams_by_code, cfg, events):
    """Append point events (pre-multiplier) for both teams of a finished match."""
    date = match["utcDate"][:10]
    score = match["score"]
    hg, ag = match_goals(score)
    winner = score.get("winner")
    pens = score.get("duration") == "PENALTY_SHOOTOUT"
    tier = {c: teams_by_code[c]["tier"] for c in (code_home, code_away)}

    per_team_match_pts = {}
    for code, opp, gf, ga, is_home in (
        (code_home, code_away, hg, ag, True),
        (code_away, code_home, ag, hg, False),
    ):
        pts = []
        won = winner == ("HOME_TEAM" if is_home else "AWAY_TEAM")
        drew = winner == "DRAW"
        lost_shootout = pens and not won

        if won:
            pts.append((cfg["win"], "Win" + (" (on penalties)" if pens else "")))
        elif drew:
            pts.append((cfg["draw"], "Draw"))
        elif lost_shootout:
            pts.append((cfg["shootout_loss"], "Penalty shootout loss (counts as draw)"))

        if gf:
            pts.append((cfg["goal"] * gf, f"{gf} goal{'s' if gf > 1 else ''}"))
        if ga == 0:
            pts.append((cfg["clean_sheet"], "Clean sheet"))

        gap = tier[code] - tier[opp]  # positive => this team is the underdog
        if gap > 0:
            if won:
                pts.append((cfg["upset_win_per_tier_gap"] * gap,
                            f"Upset! Beat a Tier {tier[opp]} team"))
            elif drew or lost_shootout:
                pts.append((cfg["upset_draw_per_tier_gap"] * gap,
                            f"Held a Tier {tier[opp]} team"))

        for value, desc in pts:
            events[code].append({"date": date, "points": value, "desc": desc, "kind": "match"})
        per_team_match_pts[code] = sum(v for v, _ in pts)
    return per_team_match_pts


def add_progression_events(matches_resolved, teams_by_code, cfg, events):
    """Award stage-reached bonuses, dated by the team's first match in that stage."""
    first_in_stage = {}  # (code, stage) -> date
    final = None
    for m, ch, ca in matches_resolved:
        stage = m["stage"]
        if stage == "FINAL":
            final = (m, ch, ca)
        if stage not in cfg["progression"]:
            continue
        for code in (ch, ca):
            if code:
                key = (code, stage)
                date = m["utcDate"][:10]
                if key not in first_in_stage or date < first_in_stage[key]:
                    first_in_stage[key] = date

    for (code, stage), date in first_in_stage.items():
        events[code].append({
            "date": date, "points": cfg["progression"][stage],
            "desc": f"Reached the {STAGE_LABELS[stage]}", "kind": "progression",
        })

    if final and final[0]["status"] == "FINISHED":
        m, ch, ca = final
        winner = m["score"].get("winner")
        champ = ch if winner == "HOME_TEAM" else ca if winner == "AWAY_TEAM" else None
        if champ:
            events[champ].append({
                "date": m["utcDate"][:10], "points": cfg["progression"]["CHAMPION"],
                "desc": "WORLD CHAMPIONS", "kind": "progression",
            })
            teams_by_code[champ]["_champion"] = True


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
    if mode == "live":
        if not token:
            sys.exit("Set FOOTBALL_DATA_TOKEN (free key: https://www.football-data.org/client/register)\n"
                     "or run with --offline / --demo.")
        matches = fetch_matches(token)
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
    multiplier = {c: cfg["multipliers"][str(teams_by_code[c]["tier"])] for c in teams_by_code}

    for m, ch, ca in matches_resolved:
        if m["status"] != "FINISHED" or not ch or not ca:
            continue
        raw_pts = score_match(m, ch, ca, teams_by_code, cfg, events)
        hg, ag = match_goals(m["score"])
        pens = m["score"].get("duration") == "PENALTY_SHOOTOUT"
        note = ""
        if pens:
            p = m["score"].get("penalties")
            note = f" ({p['home']}-{p['away']} pens)" if p else " (pens)"
        results.append({
            "id": m.get("id"),
            "date": m["utcDate"][:10],
            "utc": m["utcDate"],
            "stage": STAGE_LABELS.get(m["stage"], m["stage"]),
            "group": (m.get("group") or "").replace("_", " ").title() or None,
            "note": note,
            "home": {"code": ch, "name": teams_by_code[ch]["name"], "flag": teams_by_code[ch]["flag"],
                     "tier": teams_by_code[ch]["tier"], "goals": hg,
                     "points": round(raw_pts[ch] * multiplier[ch], 1)},
            "away": {"code": ca, "name": teams_by_code[ca]["name"], "flag": teams_by_code[ca]["flag"],
                     "tier": teams_by_code[ca]["tier"], "goals": ag,
                     "points": round(raw_pts[ca] * multiplier[ca], 1)},
        })

    add_progression_events(matches_resolved, teams_by_code, cfg, events)
    status = compute_status(matches_resolved, teams_by_code)
    groups = compute_groups(matches_resolved, teams_by_code, owner)

    # Match details, top scorers, odds
    if mode == "live":
        update_details(token, matches_resolved, index)
        scorers = fetch_scorers(token, index, teams_by_code, owner)
        extras = fetch_espn_extras(index)
    elif mode == "demo":
        finished_demo = [(m, ch, ca) for m, ch, ca in matches_resolved if m["status"] == "FINISHED"]
        (ROOT / "docs/details.json").write_text(
            json.dumps(demo_details(finished_demo, teams_by_code), ensure_ascii=False) + "\n")
        scorers = [{**s, "flag": teams_by_code[s["team"]]["flag"],
                    "owner": owner.get(s["team"])} for s in DEMO_SCORERS]
        extras = DEMO_EXTRAS
    else:
        (ROOT / "docs/details.json").write_text("{}\n")
        scorers = []
        extras = {}

    # Per-team totals and W/D/L records
    team_out = {}
    for code, t in teams_by_code.items():
        evs = sorted(events[code], key=lambda e: e["date"])
        total = round(sum(e["points"] for e in evs) * multiplier[code], 1)
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
            "fifa_rank": t["fifa_rank"], "multiplier": multiplier[code],
            "owner": owner.get(code), "status": status[code],
            "played": len(played), "won": won, "drawn": drawn, "lost": lost,
            "gf": gf, "ga": ga, "total": total,
            "events": [{"date": e["date"],
                        "desc": e["desc"],
                        "points": round(e["points"] * multiplier[code], 1)}
                       for e in sorted(evs, key=lambda e: e["date"], reverse=True)],
        }

    # Player totals, plus "latest matchday" delta and movement
    finished_dates = sorted({r["date"] for r in results})
    latest_day = finished_dates[-1] if finished_dates else None

    def player_total(p, before=None):
        tot = 0.0
        for code in p.get("teams", []):
            for e in events[code]:
                if before is None or e["date"] < before:
                    tot += e["points"] * multiplier[code]
        return round(tot, 1)

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

    upcoming = []
    for m, ch, ca in matches_resolved:
        if m["status"] in ("SCHEDULED", "TIMED") and ch and ca:
            extra = extras.get((m["utcDate"][:10], frozenset((ch, ca))), {})
            form = extra.get("form") or {}
            upcoming.append({
                "utc": m["utcDate"],
                "stage": STAGE_LABELS.get(m["stage"], m["stage"]),
                "group": (m.get("group") or "").replace("_", " ").title() or None,
                "odds": extra.get("odds"),
                "home": {"name": teams_by_code[ch]["name"], "flag": teams_by_code[ch]["flag"],
                         "owner": owner.get(ch), "form": form.get(ch)},
                "away": {"name": teams_by_code[ca]["name"], "flag": teams_by_code[ca]["flag"],
                         "owner": owner.get(ca), "form": form.get(ca)},
            })
    upcoming.sort(key=lambda u: u["utc"])

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "latest_day": latest_day,
        "scoring": cfg,
        "players": players_out,
        "teams": team_out,
        "results": sorted(results, key=lambda r: r["utc"], reverse=True),
        "upcoming": upcoming[:12],
        "groups": groups,
        "scorers": scorers,
    }
    (ROOT / "docs/data.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"Wrote docs/data.json ({mode} mode): {len(results)} finished matches, "
          f"latest matchday {latest_day or 'n/a'}")


if __name__ == "__main__":
    main()
