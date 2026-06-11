#!/usr/bin/env python3
"""Run the sweepstake draw: assign 3 teams to each of the 16 players.

The 48 teams are ranked by FIFA world ranking and split into three tiers of 16
(Tier 1 = ranks 1-16, etc.). Every player draws ONE team from EACH tier, so
everyone gets a favourite, a mid-ranker and an underdog — that balance is what
keeps the flat scoring system fair.

Usage:
    python scripts/draw.py            # random draw
    python scripts/draw.py 2026      # seeded draw (reproducible, auditable)

Edit the player names in data/players.json BEFORE running the draw.
Re-running overwrites previous assignments.
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    teams = json.loads((ROOT / "data/teams.json").read_text())["teams"]
    players_doc = json.loads((ROOT / "data/players.json").read_text())
    players = players_doc["players"]

    if len(players) != 16:
        sys.exit(f"Expected 16 players in data/players.json, found {len(players)}")

    rng = random.Random(int(sys.argv[1])) if len(sys.argv) > 1 else random.Random()

    tiers = {t: [team["code"] for team in teams if team["tier"] == t] for t in (1, 2, 3)}
    for pool in tiers.values():
        rng.shuffle(pool)

    by_code = {t["code"]: t for t in teams}
    for player in players:
        player["teams"] = [tiers[1].pop(), tiers[2].pop(), tiers[3].pop()]

    (ROOT / "data/players.json").write_text(json.dumps(players_doc, indent=2) + "\n")

    print(f"{'Player':<20} Teams")
    print("-" * 70)
    for p in players:
        names = ", ".join(
            f"{by_code[c]['flag']} {by_code[c]['name']} (T{by_code[c]['tier']})" for c in p["teams"]
        )
        print(f"{p['name']:<20} {names}")
    print("\nDraw saved to data/players.json")
    print("Now run: python scripts/update_scores.py --offline  (to refresh the page data)")


if __name__ == "__main__":
    main()
