# World Cup 2026 Sweepstake

A self-updating sweepstake tracker for the 2026 FIFA World Cup: 48 teams,
24 players, underdog-friendly scoring, and a leaderboard webpage that
refreshes itself every few hours via GitHub Actions + GitHub Pages.

## How it works

- `data/teams.json` — the 48 qualified teams with their pre-tournament FIFA
  ranking, split into three tiers of 16 (Tier 1 = ranks 1–16, etc.).
- `data/players.json` — your 24 players and their drawn teams.
- `scripts/draw.py` — runs the draw: every player gets 2 teams from two
  *different* tiers (8 players get T1+T2, 8 get T1+T3, 8 get T2+T3).
- `scripts/update_scores.py` — pulls results from football-data.org, scores
  every finished match, and writes `docs/data.json`.
- `docs/index.html` — the leaderboard page (works as a plain static file).
- `.github/workflows/update.yml` — cron job that re-runs the updater every
  3 hours and commits the new scores.

## Scoring

Every point a team earns is **multiplied by its tier**: Tier 1 ×1,
Tier 2 ×1.5, Tier 3 ×2 — so a plucky minnow can out-earn a giant.

| Event | Points (before multiplier) |
|---|---|
| Win (incl. shootout win) | 3 |
| Draw / losing a shootout | 1 |
| Each goal scored | 1 |
| Clean sheet | 1 |
| **Upset bonus** — beating a higher-tier team | +4 per tier gap |
| Upset draw — holding a higher-tier team | +2 per tier gap |
| Reach R32 / R16 / QF / SF / Final | +4 / +6 / +8 / +10 / +12 |
| Win the World Cup | +15 |

Example: a Tier 3 team beats a Tier 1 team 2–1 → (3 + 2 + 8) × 2 = **26 pts**.
All numbers are tunable in `data/scoring.json` (change them *before* the
tournament starts — every run recomputes from scratch, so mid-tournament
changes rewrite history).

## Setup (one-time, ~10 minutes)

1. **Name your players** — edit the 24 names in `data/players.json`.

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

| Source | What it provides | Key needed? |
|---|---|---|
| [football-data.org](https://www.football-data.org) | Results, fixtures, stages (drives all scoring), match detail: goalscorers, cards, subs, line-ups, stats where available | Free key (10 req/min) |
| ESPN public API | Live 1X2 + over/under odds (DraftKings) and recent form for upcoming fixtures | None |

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
