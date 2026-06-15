# Setup: API Keys & Tooling Access

Practical setup notes for the pipeline. **Never commit keys to git** — use
environment variables or a local `.env` that's git-ignored.

## YouTube Data API v3 (metadata + competitor research)

Free key, ~5 minutes:

1. Sign in to the **[Google Cloud Console](https://console.cloud.google.com)**
   (ideally a Google account dedicated to the channel).
2. **Create a project** — project dropdown → *New Project* → name it
   (e.g. "F1 Channel Tooling") → *Create* → select it.
3. **Enable the API** — *APIs & Services → Library* → search
   **"YouTube Data API v3"** → **Enable**.
4. **Create credentials** — *APIs & Services → Credentials* →
   *Create Credentials* → **API key** → copy it.
5. **Restrict the key** — open the key → *API restrictions* →
   **Restrict key → YouTube Data API v3** → Save. (Optionally restrict by IP for
   a server.)
6. **Use it** — `?key=YOUR_KEY` on requests, or env var `YOUTUBE_API_KEY`.

### Quota
- Free tier: **10,000 units/day**.
- `search.list` = **100 units** (~100 searches/day); most `*.list` reads
  (videos, channels, playlistItems) = **1 unit**. Ample for our needs.
- Request a quota increase later if scaling.

### What the API does and doesn't give you
- ✅ **Metadata**: video titles, view/like/comment counts, durations, channel
  stats, search results, a channel's top/most-recent videos. → powers the
  competitor spreadsheet and the harvest stage's "what's being watched" signal.
- ❌ **Transcripts of other people's videos**: `captions.download` only works for
  videos **you own** (via OAuth). For others' spoken scripts use the free tools
  below.

## Transcripts (the "Listen" stage)

- **`youtube-transcript-api`** (Python) — pulls existing/auto captions, no key.
- **`yt-dlp --write-auto-sub --skip-download`** — fetch auto-captions.
- **Whisper** (OpenAI, local or API) — transcribe audio when captions are
  absent.

> Reminder (`03`): transcripts are **research signal only** — themes/gaps, never
> reproduced. Keep request volumes reasonable to respect YouTube's ToS.

## Other keys you'll likely need later

| Tool | Purpose | Notes |
|---|---|---|
| TTS (e.g. ElevenLabs-class) | Narration voice | Use a rights-cleared/custom voice; keep it consistent |
| LLM API (Claude — latest models) | Synthesis & scripting | Long-context synthesis of many transcripts → one original angle |
| Stock/footage library | Green-tier visuals | Licence must cover monetised YouTube |

## Secret hygiene
- Store keys in env vars or a git-ignored `.env`; never hardcode.
- Add `.env` to `.gitignore` before writing any script.
- Rotate a key immediately if it's ever exposed.
