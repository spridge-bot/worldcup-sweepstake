#!/usr/bin/env python3
"""
Competitor research for the F1 channel — pulls public metadata from the
YouTube Data API v3.

What it does
------------
For each channel:
  * resolves the channel (by ID `UC...`, by handle `@name`, or by search term)
  * fetches channel stats (subscribers, total views, video count)
  * fetches that channel's top videos by all-time view count
  * enriches each video with exact stats + duration

It also has a `harvest` mode: top videos for a search QUERY (the "Listen"
stage of the pipeline — what's being watched on a topic right now).

Output
------
  out/competitor_videos.csv      one row per video
  out/competitor_channels.csv    one row per channel
  out/competitor_summary.md      readable top-10-per-channel tables
  (harvest mode) out/harvest_<slug>.csv

Usage
-----
  export YOUTUBE_API_KEY=...                      # never hardcode the key
  python3 competitor_research.py                  # default channel list
  python3 competitor_research.py @Driver61 UC7u-Dg0jb7g9s7XjmtJrtpg
  python3 competitor_research.py --top 25 "Chain Bear" "Aldas F1"
  python3 competitor_research.py --harvest "f1 strategy explained" --top 30

Quota note: each channel costs ~100 units (one search.list) + a couple of
1-unit reads. The free tier is 10,000 units/day, so this is cheap.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError
import json

API = "https://www.googleapis.com/youtube/v3"
OUT = Path(__file__).resolve().parent / "out"

# Default competitors (mix of faceless/graphics-led peers + The Race benchmark).
DEFAULT_CHANNELS = [
    "UCaTxfj0BzL-MaCy-YUqPRoQ",  # The Race
    "UC7u-Dg0jb7g9s7XjmtJrtpg",  # Chain Bear (faceless, animated)
    "@Driver61",                  # Driver61 (infographic-led)
    "Aldas F1",                   # resolved by search
]


def api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        sys.exit("ERROR: set YOUTUBE_API_KEY in your environment (do not hardcode it).")
    return key


def get(endpoint: str, **params) -> dict:
    params["key"] = api_key()
    url = f"{API}/{endpoint}?{urlencode(params)}"
    try:
        with urlopen(url) as r:
            return json.load(r)
    except HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        sys.exit(f"API error {e.code} on {endpoint}: {body[:500]}")


def resolve_channel_id(token: str) -> str | None:
    """Accept a channel ID, an @handle, or a free-text search term."""
    token = token.strip()
    if re.fullmatch(r"UC[\w-]{22}", token):
        return token
    if token.startswith("@"):
        data = get("channels", part="id", forHandle=token)
        items = data.get("items") or []
        if items:
            return items[0]["id"]
    # Fall back to search.
    data = get("search", part="snippet", q=token, type="channel", maxResults=1)
    items = data.get("items") or []
    return items[0]["snippet"]["channelId"] if items else None


def channel_info(channel_id: str) -> dict:
    data = get("channels", part="snippet,statistics", id=channel_id)
    items = data.get("items") or []
    if not items:
        return {}
    it = items[0]
    s = it.get("statistics", {})
    return {
        "channel_id": channel_id,
        "title": it["snippet"]["title"],
        "subscribers": int(s.get("subscriberCount", 0)) if not s.get("hiddenSubscriberCount") else None,
        "total_views": int(s.get("viewCount", 0)),
        "video_count": int(s.get("videoCount", 0)),
    }


def top_video_ids(channel_id: str, n: int) -> list[str]:
    """Top videos by all-time views (search.list order=viewCount)."""
    ids: list[str] = []
    page = None
    while len(ids) < n:
        params = dict(part="id", channelId=channel_id, type="video",
                      order="viewCount", maxResults=min(50, n - len(ids)))
        if page:
            params["pageToken"] = page
        data = get("search", **params)
        ids += [x["id"]["videoId"] for x in data.get("items", []) if x["id"].get("videoId")]
        page = data.get("nextPageToken")
        if not page:
            break
    return ids[:n]


def search_video_ids(query: str, n: int, order: str = "viewCount") -> list[str]:
    ids: list[str] = []
    page = None
    while len(ids) < n:
        params = dict(part="id", q=query, type="video", order=order,
                      maxResults=min(50, n - len(ids)))
        if page:
            params["pageToken"] = page
        data = get("search", **params)
        ids += [x["id"]["videoId"] for x in data.get("items", []) if x["id"].get("videoId")]
        page = data.get("nextPageToken")
        if not page:
            break
    return ids[:n]


def iso_duration(d: str) -> str:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return ""
    h, mn, s = (int(x) if x else 0 for x in m.groups())
    return f"{h}:{mn:02d}:{s:02d}" if h else f"{mn}:{s:02d}"


def video_details(video_ids: list[str]) -> list[dict]:
    rows: list[dict] = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        data = get("videos", part="snippet,statistics,contentDetails", id=",".join(batch))
        for it in data.get("items", []):
            st = it.get("statistics", {})
            rows.append({
                "video_id": it["id"],
                "title": it["snippet"]["title"],
                "channel": it["snippet"]["channelTitle"],
                "published": it["snippet"]["publishedAt"][:10],
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)) if "likeCount" in st else None,
                "comments": int(st.get("commentCount", 0)) if "commentCount" in st else None,
                "duration": iso_duration(it["contentDetails"]["duration"]),
                "url": f"https://youtu.be/{it['id']}",
            })
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def fmt(n) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def run_channels(tokens: list[str], top: int) -> None:
    all_videos: list[dict] = []
    channels: list[dict] = []
    md = ["# Competitor research — top videos by channel\n"]
    for token in tokens:
        cid = resolve_channel_id(token)
        if not cid:
            print(f"  ! could not resolve: {token}", file=sys.stderr)
            continue
        info = channel_info(cid)
        channels.append(info)
        ids = top_video_ids(cid, top)
        vids = sorted(video_details(ids), key=lambda r: r["views"], reverse=True)
        all_videos += vids
        print(f"  ✓ {info.get('title', token)}: {len(vids)} videos "
              f"({fmt(info.get('subscribers'))} subs)")
        md.append(f"\n## {info.get('title', token)}  "
                  f"— {fmt(info.get('subscribers'))} subs · "
                  f"{fmt(info.get('total_views'))} views · "
                  f"{info.get('video_count', '?')} videos\n")
        md.append("| # | Views | Len | Published | Title |")
        md.append("|---|------:|-----|-----------|-------|")
        for i, v in enumerate(vids[:min(top, 15)], 1):
            t = v["title"].replace("|", "\\|")
            md.append(f"| {i} | {fmt(v['views'])} | {v['duration']} | {v['published']} | [{t}]({v['url']}) |")

    write_csv(OUT / "competitor_videos.csv", all_videos,
              ["channel", "title", "views", "likes", "comments", "duration", "published", "video_id", "url"])
    write_csv(OUT / "competitor_channels.csv", channels,
              ["title", "subscribers", "total_views", "video_count", "channel_id"])
    (OUT / "competitor_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT}/competitor_videos.csv, competitor_channels.csv, competitor_summary.md")


def run_harvest(query: str, top: int) -> None:
    ids = search_video_ids(query, top)
    vids = sorted(video_details(ids), key=lambda r: r["views"], reverse=True)
    slug = re.sub(r"\W+", "-", query.lower()).strip("-")
    write_csv(OUT / f"harvest_{slug}.csv", vids,
              ["title", "channel", "views", "likes", "comments", "duration", "published", "video_id", "url"])
    print(f"Top videos for '{query}':")
    for v in vids[:15]:
        print(f"  {fmt(v['views']):>7}  {v['duration']:>6}  {v['channel'][:22]:22}  {v['title'][:60]}")
    print(f"\nWrote {OUT}/harvest_{slug}.csv")


def main() -> None:
    ap = argparse.ArgumentParser(description="F1 channel competitor research via YouTube Data API")
    ap.add_argument("channels", nargs="*", help="channel IDs, @handles, or search terms")
    ap.add_argument("--top", type=int, default=20, help="videos per channel / harvest results")
    ap.add_argument("--harvest", metavar="QUERY", help="harvest top videos for a search query instead")
    args = ap.parse_args()

    if args.harvest:
        run_harvest(args.harvest, args.top)
    else:
        run_channels(args.channels or DEFAULT_CHANNELS, args.top)


if __name__ == "__main__":
    main()
