# Competitor Data Findings (live YouTube API pull)

Generated from `tools/competitor_research.py` against the YouTube Data API on
**2026-06-15**. Raw data: `tools/out/competitor_videos.csv` (git-ignored).
Re-run any time to refresh.

> **Data-quality note:** all-time top-video data is reliable for the three
> graphics-led peers. For **The Race** the API's `search` endpoint returned only
> *recent* uploads (not all-time tops) — a known limitation on very large
> channels (3,506 videos). Treat The Race's per-video numbers below as
> "recent form," not all-time. The peers are our real comparison set anyway.

## Channel snapshot

| Channel | Subs | Total views | Videos | Views/video (rough) | Format |
|---|---:|---:|---:|---:|---|
| **Driver61** | 1.5M | 359M | 408 | ~880K | Infographic explainers, presenter-led |
| **The Race** | 1.3M | 888M | 3,506 | ~253K | News/analysis, journalists, high volume |
| **Chain Bear** | 536K | 77M | 209 | **~370K** | **Fully faceless, animated explainers** |
| **Aldas** | 183K | 64M | 622 | ~103K | Faceless-ish, opinion/story |

**The standout for us:** Chain Bear — **faceless, only 209 videos, yet ~370K
views/video** and 77M total. Lower volume, high quality, compounding. That's the
exact efficiency profile a semi-automated faceless channel should target.

## What the top videos actually are

### Chain Bear (our closest peer — faceless, animated) — the headline finding
Its all-time top videos are **evergreen explainers from 2017–2019 that are STILL
the top performers in 2026**:
- "Racing Lines explained" (2018) — **5.5M**
- "The art of overtaking in F1" (2018) — 3.5M
- "Basics of F1 Race Strategy" (2017) — 1.8M
- "F1 Braking Systems", "Tyre wear explained", "How do Wet Tyres work?", "The
  anatomy of an F1 pitstop"…

➡️ **This is hard proof the evergreen-explainer strategy compounds for years.**
A clip-free, animated, faceless channel built a 536K-sub business on ~200
explainer videos. This validates our entire compliant-first, graphics-led plan.

### Driver61 (infographic-led) — what overperforms
Biggest hits cluster around three framings:
- **"Banned"**: "The Incredible F1 Suspension So Good It Was Banned" (5.3M),
  "Why This Genius Race Car Was Banned" (4.7M).
- **"What if / no rules"**: "What If Formula 1 Had No Rules?" (5.8M), "Pikes
  Peak: Racing with NO RULES" (5.3M).
- **Cross-motorsport curiosity**: "How NASCAR was FASTER than Ferrari at Le
  Mans" (7.5M), "How Fast Would F1 Go at the Indy 500?" (4.8M).
- Plus deep tech ("How F1 Brakes Work", "How F1 Pistons Are Made").

➡️ **Curiosity-gap framings ("banned", "what if", "how fast would…") and
broadening beyond pure F1 into wider motorsport raise the view ceiling
dramatically.** Most hits are 10–26 min — long-form explainers travel.

### Aldas (faceless-ish, opinion/story) — the story lane
Top videos are **narrative/drama**:
- "The Craziest F1 Team Owner You've Never Heard Of" (370K)
- "The Downfall of McLaren / Williams" series
- "How Bad Was Jolyon Palmer in F1?", "What's Behind the Verstappen–Perez Drama?"
- Team/driver rankings; season predictions.

➡️ **"Downfall of…", "How bad/good was…", "the X drama", and ranking videos**
are repeatable story formats that work without footage. Smaller numbers, but a
deep catalogue (622 videos) and strong opinion-led voice.

### The Race (recent form only)
Recent winners skew to **timely analysis + reaction Shorts**: "Why furious F1
team wants Monaco GP result overturned", "The driving problem deciding the F1
title", "What's really going on with Leclerc's braking nightmare", plus sub-60s
Shorts on breaking news. Confirms their lane = speed + access + footage — the
lane we deliberately avoid.

## Cross-channel patterns → decisions for us

1. **Evergreen explainers are the foundation** (Chain Bear's 2018 videos still
   top in 2026). Build a deep, compounding back-catalogue. *Already in plan —
   now evidence-backed; raise its priority.*
2. **Curiosity-gap framings win**: "banned", "what if", "the genius/forgotten…",
   "how fast would…", "the downfall of…". → Bake these title patterns into
   `content-idea-bank.md`.
3. **Strategy & tech explainers are reliable, graphics-native winners** (Chain
   Bear's strategy/braking/tyre videos; Driver61's tech deep-dives). → Confirms
   "Strategy" as a flagship series.
4. **Story/drama works faceless** (Aldas). → Our Drama pillar has a proven model:
   "Downfall of…", "How bad was…", rankings.
5. **Long-form travels** — most mega-hits are 8–26 min, not Shorts. → Shorts for
   funnel, long-form for the value + watch-time.
6. **Broadening into wider motorsport lifts the ceiling** (Driver61's biggest
   video is NASCAR-vs-Ferrari). → Optional: occasional adjacent-motorsport
   explainers once established, to tap bigger curiosity audiences.
7. **Faceless + low-volume + high-quality is a viable business** (Chain Bear).
   → Validates the semi-automated, quality-gated model over volume spam.

## How to refresh / extend this

```bash
export YOUTUBE_API_KEY=...            # your key, never committed
cd f1-youtube-channel/tools
python3 competitor_research.py --top 25            # default 4 channels
python3 competitor_research.py @SomeChannel "Search Term"   # custom set
python3 competitor_research.py --harvest "f1 strategy explained" --top 30
```

Next data steps worth running:
- `--harvest` on our candidate pilot topics to size demand before we script.
- Add 2–3 more faceless/graphics peers once identified.
- Pull comment threads on top peer videos (manual) to find unanswered questions
  = our video ideas.
