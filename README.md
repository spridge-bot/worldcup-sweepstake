# World Cup 2026 Sweepstake

A self-updating sweepstake tracker for the 2026 FIFA World Cup: 48 teams,
12 players × 4 teams each, balanced flat scoring, and a leaderboard webpage
that refreshes itself every few hours via GitHub Actions + GitHub Pages.

## How it works

- `data/teams.json` — the 48 qualified teams with their pre-tournament FIFA
  ranking, split into four pots of 12 (Pot 1 = the top 12, Pot 2 = 13th–24th,
  Pot 3 = 25th–36th, Pot 4 = 37th–48th).
- `data/players.json` — the 12 players and their drawn teams.
- The draw is run live on `docs/draw.html` (one team from each pot per player);
  `scripts/draw.py` is the offline/CLI equivalent.
- `scripts/update_scores.py` — pulls results from football-data.org, scores
  every finished match, and writes `docs/data.json`.
- `docs/index.html` — the leaderboard page (works as a plain static file).
- `.github/workflows/update.yml` — cron job that re-runs the updater every
  3 hours and commits the new scores.

## Scoring

Balance comes from the draw — every player holds one team from each pot —
so the points are flat and simple, no multipliers.

| Event | Points |
|---|---|
| Finish 1st in your group | 5 |
| Finish 2nd | 3 |
| Finish 3rd | 1 |
| Finish 4th | 0 |
| Win your Round of 32 tie | +2 |
| Win in the Round of 16 | +3 |
| Win your quarter-final | +4 |
| Win your semi-final | +5 |
| Win the final | +6 |

The average team earns ~2.25 points in the group stage; a champion banks a
maximum of 25 (5 + 2 + 3 + 4 + 5 + 6). Group positions are scored *live* as
games finish and lock in when the group completes. Shootout wins count as
wins; the third-place play-off carries no points. All numbers are tunable in
`data/scoring.json` (change them *before* the tournament starts — every run
recomputes from scratch, so mid-tournament changes rewrite history).

## Setup (one-time, ~10 minutes)

1. **Name your players** — edit the 12 names in `data/players.json`.

2. **Run the draw** (optionally with a seed so it's reproducible/auditable):

   ```sh
   python3 scripts/draw.py 2026
   python3 scripts/update_scores.py --offline   # regenerate the page data
   ```

3. **Get a free API key** at
   [football-data.org/client/register](https://www.football-data.org/client/register)
   (the free tier includes the World Cup).

4. **Push to GitHub:**

   ```sh
   gh repo create worldcup-sweepstake --public --source . --push
   ```

   (or create a repo on github.com and `git push` to it).

5. **Add the API key as a secret:** repo → Settings → Secrets and variables →
   Actions → New repository secret, name `FOOTBALL_DATA_TOKEN`, value = your key.
   Or: `gh secret set FOOTBALL_DATA_TOKEN`

6. **Enable GitHub Pages:** repo → Settings → Pages → Source: *Deploy from a
   branch*, Branch: `main`, folder `/docs`. Your page goes live at
   `https://<your-username>.github.io/worldcup-sweepstake/` — share that URL
   with the players.

7. **Test the pipeline:** repo → Actions → *Update sweepstake scores* →
   *Run workflow*. It will fetch results, commit `docs/data.json`, and Pages
   redeploys automatically. After that it runs itself every 3 hours.

## Local preview

```sh
python3 scripts/update_scores.py --demo    # fake results to see scoring in action
python3 -m http.server -d docs 8000       # open http://localhost:8000
```

Run with `--offline` to reset back to a blank slate, or with a real
`FOOTBALL_DATA_TOKEN=... python3 scripts/update_scores.py` for live data.

## Data sources

**No API key is required.** Without `FOOTBALL_DATA_TOKEN` the updater runs
entirely on ESPN's keyless public API: full real schedule, group letters,
live scores, goalscorers/cards, odds, stats and line-ups. Adding a free
football-data.org key upgrades the goal/card/sub timelines and the official
Golden Boot feed.

| Source | What it provides | Key needed? |
|---|---|---|
| ESPN public API (scoreboard + standings) | Real groups & full schedule, live scores, key events (goals/cards/shootouts), 1X2 + over/under odds (DraftKings), recent form, venues | None |
| ESPN public API (summary) | Deep match stats (possession, shots, passes, pass accuracy, crosses, long balls, corners, fouls, saves...), full line-ups with formations, venue/attendance/referee — merged into every finished match | None |
| [football-data.org](https://www.football-data.org) | Optional upgrade: official results/stages, richer match detail (subs, referee, official scorer feed) | Free key (10 req/min) |

To check whether an **API-Football** (api-sports.io) free key is worth adding:
sign up at [dashboard.api-football.com/register](https://dashboard.api-football.com/register),
then run `API_FOOTBALL_KEY=yourkey python3 scripts/test_api_football.py` — it
reports whether your key can see World Cup 2026 (free plans usually exclude
the current season).

Match details are rate-limited, so `docs/details.json` fills in incrementally —
the newest 25 un-detailed matches are fetched per run and cached forever.

Alternatives if you ever want to switch: **API-Football** (api-sports.io, free
100 req/day, very rich stats/lineups/odds), **The Odds API**
(the-odds-api.com, free 500 credits/month, multi-bookmaker odds),
**TheSportsDB** (free, thinner data). ESPN's API is unofficial — if it ever
changes shape, odds/form quietly disappear but scoring is unaffected.

## Notes

- Scores are recomputed from the full match list on every run, so the system
  is self-healing — a missed cron run or corrected result fixes itself.
- A penalty-shootout loss counts as a draw (they didn't lose in 120 minutes).
- "Latest" column on the leaderboard = points earned on the most recent
  matchday; the ▲▼ arrows show ranking movement caused by that matchday.
