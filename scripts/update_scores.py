#!/usr/bin/env python3
"""Fetch World Cup 2026 results, score the sweepstake, write docs/data.json.

Usage:
    FOOTBALL_DATA_TOKEN=xxx python scripts/update_scores.py   # live results
    python scripts/update_scores.py --offline                 # no results yet, just render the draw
    python scripts/update_scores.py --demo                    # fake results to preview the scoring

Get a free API token at https://www.football-data.org/client/register
(the free tier includes the FIFA World Cup).

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
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://api.football-data.org/v4/competitions/WC/matches"

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
    for key in (api_team.get("name"), api_team.get("shortName"), api_team.get("tla")):
        if key and normalize(key) in index:
            return index[normalize(key)]
    return None


def fetch_matches(token):
    req = urllib.request.Request(API_URL, headers={"X-Auth-Token": token})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["matches"]


def demo_matches():
    """A fake first two matchdays so you can preview how scoring plays out."""
    def m(date, stage, home, away, hg, ag, winner, duration="REGULAR"):
        return {
            "utcDate": f"{date}T18:00:00Z",
            "status": "FINISHED",
            "stage": stage,
            "homeTeam": {"name": home},
            "awayTeam": {"name": away},
            "score": {"winner": winner, "duration": duration,
                      "fullTime": {"home": hg, "away": ag}},
        }
    return [
        m("2026-06-11", "GROUP_STAGE", "Mexico", "South Africa", 2, 0, "HOME_TEAM"),
        m("2026-06-11", "GROUP_STAGE", "Haiti", "Belgium", 1, 1, "DRAW"),
        m("2026-06-12", "GROUP_STAGE", "New Zealand", "Argentina", 2, 1, "HOME_TEAM"),
        m("2026-06-12", "GROUP_STAGE", "USA", "Paraguay", 3, 0, "HOME_TEAM"),
        m("2026-06-12", "GROUP_STAGE", "Japan", "Germany", 2, 1, "HOME_TEAM"),
        m("2026-06-12", "GROUP_STAGE", "France", "Ghana", 4, 0, "HOME_TEAM"),
    ]


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
            events[code].append({"date": date, "points": value, "desc": desc,
                                 "kind": "match", "match_id": id(match)})
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

    if mode == "live":
        token = os.environ.get("FOOTBALL_DATA_TOKEN")
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
            shootout = f" ({p['home']}-{p['away']} pens)" if p else " (decided on penalties)"
            note = shootout
        results.append({
            "date": m["utcDate"][:10],
            "utc": m["utcDate"],
            "stage": STAGE_LABELS.get(m["stage"], m["stage"]),
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
            upcoming.append({
                "utc": m["utcDate"],
                "stage": STAGE_LABELS.get(m["stage"], m["stage"]),
                "home": {"name": teams_by_code[ch]["name"], "flag": teams_by_code[ch]["flag"],
                         "owner": owner.get(ch)},
                "away": {"name": teams_by_code[ca]["name"], "flag": teams_by_code[ca]["flag"],
                         "owner": owner.get(ca)},
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
    }
    (ROOT / "docs/data.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"Wrote docs/data.json ({mode} mode): {len(results)} finished matches, "
          f"latest matchday {latest_day or 'n/a'}")


if __name__ == "__main__":
    main()
