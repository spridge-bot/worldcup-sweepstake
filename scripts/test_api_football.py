#!/usr/bin/env python3
"""Probe what an API-Football (api-sports.io) key can actually see.

API-Football's free plan is documented as "limited in terms of available
seasons" — historically that excludes the CURRENT season, which would make it
useless for World Cup 2026. This script tells you definitively, spending only
3 of your 100 daily requests.

Usage:
    API_FOOTBALL_KEY=xxx python3 scripts/test_api_football.py

Sign up at https://dashboard.api-football.com/register (no card needed).
"""
import json
import os
import sys
import urllib.request

BASE = "https://v3.football.api-sports.io"
WORLD_CUP_LEAGUE_ID = 1


def get(path, key):
    req = urllib.request.Request(f"{BASE}{path}", headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main():
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        sys.exit("Set API_FOOTBALL_KEY first:\n"
                 "  API_FOOTBALL_KEY=yourkey python3 scripts/test_api_football.py")

    status = get("/status", key)
    acct = status.get("response", {})
    sub = acct.get("subscription", {})
    req_info = acct.get("requests", {})
    print(f"Account: {acct.get('account', {}).get('email', '?')}")
    print(f"Plan: {sub.get('plan')} (active: {sub.get('active')})")
    print(f"Requests today: {req_info.get('current')}/{req_info.get('limit_day')}")
    if status.get("errors"):
        sys.exit(f"API errors: {status['errors']}")

    league = get(f"/leagues?id={WORLD_CUP_LEAGUE_ID}", key)
    seasons = (league.get("response") or [{}])[0].get("seasons", [])
    s2026 = next((s for s in seasons if s.get("year") == 2026), None)
    print(f"\nWorld Cup seasons visible: {[s.get('year') for s in seasons]}")
    if s2026:
        cov = s2026.get("coverage", {})
        fx = cov.get("fixtures", {})
        print("2026 coverage:",
              f"events={fx.get('events')}, lineups={fx.get('lineups')},",
              f"stats={fx.get('statistics_fixtures')}, players_stats={fx.get('statistics_players')},",
              f"odds={cov.get('odds')}, predictions={cov.get('predictions')}")

    fixtures = get("/fixtures?league=1&season=2026", key)
    n = fixtures.get("results", 0)
    errs = fixtures.get("errors")
    print(f"\n2026 fixtures returned: {n}")
    if errs:
        print(f"errors: {errs}")
    if n > 0:
        print("\nVERDICT: ✅ your key CAN see World Cup 2026 — worth integrating "
              "(tell Claude and it can be wired in as another enrichment source).")
    else:
        print("\nVERDICT: ❌ your key cannot see World Cup 2026 (free plans usually "
              "exclude the current season). Stick with football-data.org + ESPN — "
              "both are already integrated and free.")


if __name__ == "__main__":
    main()
