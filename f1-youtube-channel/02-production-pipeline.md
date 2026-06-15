# 02 — Production Pipeline (Semi-Automated)

The principle: **AI does the heavy lifting; a human is the editor-in-chief.**
Every video passes through two human gates — *script approval* and *final-cut
approval* — before it publishes. That's what keeps output from going generic
and keeps you off the wrong side of YouTube's policies.

```
 ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
 │ 1 LISTEN │ → │ 2 THEME  │ → │ 3 SCRIPT │ → │ 4 VOICE  │ → │ 5 VISUAL │ → │ 6 EDIT   │ → │ 7 PUBLISH│
 │ harvest  │   │ cluster  │   │ draft +  │   │ TTS /    │   │ footage+ │   │ assemble │   │ + package│
 │ the convo│   │ + angle  │   │ ✅HUMAN  │   │ VO       │   │ graphics │   │ + ✅HUMAN│   │ + SEO    │
 └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
```

## Stage 1 — LISTEN (harvest the conversation)

Goal: find what people are actually watching, asking, and arguing about — so
every video answers real demand instead of guessing.

**Inputs to harvest:**
- **YouTube** — top/most-recent videos for target queries: their titles,
  thumbnails, view counts, and **transcripts** (the spoken script). Transcripts
  reveal which sub-topics get the most coverage and which questions go
  unanswered. *(Read the transcript-scraping caveats in `03` first.)*
- **Search demand** — autocomplete suggestions, "people also ask", trend tools
  (e.g. trends data, keyword tools) for the spike topics post-race.
- **Community** — relevant subreddits, fan forums, comment sections (what are
  people confused/angry/curious about?).
- **News/official** — race results, FIA documents, team statements (for facts,
  not framing).

**How to get transcripts (technical options):**
- YouTube Data API for metadata (titles, stats, captions list).
- `youtube-transcript-api` (Python) or `yt-dlp --write-auto-sub` to pull
  auto-captions where available.
- Whisper (local or API) to transcribe audio when captions are absent.

> ⚠️ Use harvested transcripts as **research signal only** (what topics/angles
> exist, what's missing). Do **not** reproduce another creator's script. See
> `03` for why this line matters legally and for the channel's survival.

## Stage 2 — THEME (cluster + pick the angle)

Feed the harvested material to an LLM to do the synthesis a researcher would:
1. **Cluster** the coverage into the 3–6 recurring themes of the week.
2. **Find the gaps** — questions raised but poorly answered across the top
   videos. These are your highest-value video ideas.
3. **Rank** candidate topics by *demand (search/views) × differentiation (can we
   say something others didn't) × effort*.
4. **Manufacture the angle** — for the chosen topic, generate 3 candidate
   thesis statements / non-obvious angles (a stat, a strategic read, a
   historical parallel). Human picks one.

Output of this stage: a one-line **thesis** + a chosen **pillar** + a **target
keyword/title hypothesis**. Nothing gets scripted without a thesis.

## Stage 3 — SCRIPT  ✅ human gate

LLM drafts to a fixed template (see `content-idea-bank.md`):
- **Cold open / hook** (≤5s): the stakes or the surprising claim.
- **Promise**: what the viewer will know by the end.
- **Body**: 3 signposted beats, each = claim → evidence → "so what".
- **The non-obvious angle**: the thing only this channel is saying.
- **Outro**: forward-look + a question to drive comments + soft CTA.

**Human gate (non-negotiable):** the editor-in-chief checks every script for:
- **Factual accuracy** — verify every result, name, date, quote against a
  primary source. LLMs hallucinate F1 specifics; assume nothing.
- **Originality** — does it actually have a take, or is it a rephrase of the
  source videos? Kill generic drafts.
- **Tone & brand voice** — sounds like *us*.
- **Legal** — no defamation in drama pieces (stick to reported facts + clearly
  flagged opinion), no reproduced scripts.

## Stage 4 — VOICE (narration)

- Generate VO from the approved script with your chosen TTS voice (consistent
  across all videos — it's the brand). Keep a pronunciation dictionary for
  drivers/teams/circuits the TTS mangles.
- Add light pacing edits (pauses, emphasis) — modern TTS supports this.
- Keep the raw VO track for re-edits.

## Stage 5 — VISUALS (compliant-first)

Build the picture without leaning on race clips (full detail in `03`):
- **Original motion graphics**: standings tables, telemetry-style charts, gap
  graphs, tyre-strategy diagrams, track maps, timelines. These are *your IP*,
  on-brand, and the strongest visual differentiator for analysis content.
- **Licensed/stock**: stills and B-roll from properly licensed libraries;
  Creative-Commons assets with attribution.
- **Official embeds** where appropriate (in supplementary contexts).
- **Data viz tools**: After Effects / Motion templates, or programmatic
  (e.g. Remotion, Manim-style) for repeatable chart animations.
- Maintain a **reusable asset library** (lower-thirds, transitions, stat cards)
  so each video is assembly, not from-scratch design.

## Stage 6 — EDIT  ✅ human gate

- Assemble VO + visuals to the beat of the script; cut for pace (F1 audiences
  bounce on slow intros).
- Captions/subtitles burned or as a track (accessibility + silent autoplay +
  retention).
- Music: royalty-free/licensed only.
- **Human gate:** final-cut review for accuracy of on-screen text, footage
  rights, pacing, and the thumbnail/title match (no clickbait betrayal).

## Stage 7 — PUBLISH & PACKAGE

- Title, thumbnail, description, tags, chapters, end screen, pinned comment
  (see `04-seo-and-growth.md`).
- Schedule for the audience's peak window; for news, speed matters — have a
  fast-path version of stages 3–6 for race nights.

## Tool stack (starter, swap freely)

| Job | Options |
|---|---|
| Harvest metadata | YouTube Data API, trend/keyword tools |
| Transcripts | youtube-transcript-api, yt-dlp, Whisper |
| Synthesis/scripting | Claude (latest models) — strong long-context synthesis; keep a human in the loop |
| Voice | ElevenLabs-class TTS (rights-cleared/custom voice) |
| Graphics/data-viz | After Effects/Motion, Remotion, Canva for thumbnails |
| Stock/footage | Licensed stock libraries, CC sources |
| Editing | DaVinci Resolve / Premiere / CapCut |
| Project mgmt | A simple kanban (idea → scripting → VO → edit → scheduled) |

**Note on AI tooling:** for the synthesis and scripting brains of this pipeline,
default to the latest, most capable Claude models — long-context synthesis of
many transcripts into one original angle is exactly their strength. Build the
prompts to *extract themes and gaps and propose original angles*, never to
"rewrite this transcript".

## Throughput target

Once templated, a semi-automated analysis/explainer video should be a **half-day
of human time** (angle pick + script edit + final-cut review), with AI/render
time around it. News recaps on the fast path: **1–2 hours**. Batch evergreen
history pieces in quiet weeks to bank a buffer.
