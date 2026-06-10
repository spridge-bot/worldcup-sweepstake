#!/usr/bin/env python3
"""Run the sweepstake draw: assign 2 teams to each of the 24 players.

Each player gets teams from two DIFFERENT tiers so nobody ends up with two
no-hopers or two favourites. With 16 teams per tier and 24 players this works
out exactly: 8 players draw Tier1+Tier2, 8 draw Tier1+Tier3, 8 draw Tier2+Tier3.

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

    if len(players) != 24:
        sys.exit(f"Expected 24 players in data/players.json, found {len(players)}")

    rng = random.Random(int(sys.argv[1])) if len(sys.argv) > 1 else random.Random()

    tiers = {t: [team["code"] for team in teams if team["tier"] == t] for t in (1, 2, 3)}
    for pool in tiers.values():
        rng.shuffle(pool)

    pair_types = [(1, 2)] * 8 + [(1, 3)] * 8 + [(2, 3)] * 8
    rng.shuffle(pair_types)

    by_code = {t["code"]: t for t in teams}
    for player, (ta, tb) in zip(players, pair_types):
        player["teams"] = [tiers[ta].pop(), tiers[tb].pop()]

    (ROOT / "data/players.json").write_text(json.dumps(players_doc, indent=2) + "\n")

    print(f"{'Player':<20} Teams")
    print("-" * 60)
    for p in players:
        names = ", ".join(
            f"{by_code[c]['flag']} {by_code[c]['name']} (T{by_code[c]['tier']})" for c in p["teams"]
        )
        print(f"{p['name']:<20} {names}")
    print("\nDraw saved to data/players.json")
    print("Now run: python scripts/update_scores.py --offline  (to refresh the page data)")


if __name__ == "__main__":
    main()
