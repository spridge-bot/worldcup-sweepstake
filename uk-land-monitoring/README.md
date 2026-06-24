# UK Land Monitoring — OS maps + satellite imagery for rural building activity

A toolkit + research write-up for reading detailed **Ordnance Survey** maps and
**satellite imagery**, flagging **farm-storage / industrial-storage buildings on
farmland** (Oxfordshire), and screening **how actively used** they are over time.

> **Read first:** [`docs/research-report.md`](docs/research-report.md) — the full
> research on data sources, resolution/cost/revisit trade-offs, feasibility, and
> legal/licensing notes. The one-line version is below.
>
> **Just want it running?** See [`SETUP.md`](SETUP.md). The example dashboard runs with
> zero setup (`python -m landmon.web.server`); the real pipeline needs one OS API key.
>
> **On a Mac mini?** [`MAC_SETUP.md`](MAC_SETUP.md) is a copy-paste-and-approve guide:
> one installer (`bash install_mac.sh`) does deps, key, first data build, always-on
> dashboard, weekly refresh, and Tailscale.

## The key trade-off (why this is part-free, part-paid)

| Goal | Free data (Sentinel-2/-1, Landsat) | Needs paid sub-metre (Planet/Maxar/Airbus) |
|---|---|---|
| Map & outline buildings (OS) | ✅ OS Data Hub | — |
| Flag storage buildings on farms | ✅ OS footprints + heuristics | — |
| Surrounding crop/land activity | ✅ Sentinel-2 NDVI | — |
| Detect change / construction / busy-vs-idle *trend* | ✅ Sentinel-1 SAR | — |
| **Count vehicles, see comings & goings** | ❌ (10 m ≈ bigger than a car) | ✅ 30–50 cm imagery |

So: free data does the **wide, cheap, longitudinal screen**; paid sub-metre imagery
is only for the shortlist of sites that warrant a true activity count.

## What's in here

```
docs/research-report.md     Full research + sources (start here)
config/aoi.example.geojson  Example Oxfordshire arable AOI (edit me)
src/landmon/
  aoi.py        Load/define areas of interest (WGS84 <-> British National Grid)
  os_data.py    OS Maps basemap tiles + OS NGD building/land vectors
  buildings.py  Flag farm_storage / industrial_storage buildings (heuristics)
  sentinel.py   Free Sentinel-2 NDVI & Sentinel-1 backscatter time series (PC STAC)
  change.py     Per-building activity metrics from a time series
  chips.py      Render per-building dated image chips (the filmstrip)
  web/          Zero-dependency map viewer (stdlib http.server + Leaflet)
  cli.py        Command-line pipeline
sample_data/demo_storage.geojson   Demo so the viewer renders with no key/network
```

## Setup

```bash
cd uk-land-monitoring
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # geopandas/odc-stac pull GDAL etc.
cp .env.example .env                      # add your OS_API_KEY
export PYTHONPATH=src
```

Get a free **OS Data Hub** API key at <https://osdatahub.os.uk/> (create an API
project, add OS Maps API + OS NGD API). Sentinel data via Microsoft Planetary
Computer needs no key.

## Usage

### One command, end to end (real Oxfordshire run)
With an `OS_API_KEY` set and the deps installed, this does buildings → flag storage
→ activity time series + per-date timelines → (optionally) dated image chips, writing
everything into `outputs/` ready for the viewer:

```bash
python -m landmon.cli pipeline --aoi config/aoi.example.geojson \
    --start 2023-01-01 --end 2024-12-31 --sensor s1 --chips
python -m landmon.web.server --data outputs/activity.geojson    # then open the viewer
```

### Or step by step
```bash
# 1. Discover current OS NGD collection IDs (they're versioned)
python -m landmon.cli collections

# 2. Fetch building footprints in the AOI
python -m landmon.cli buildings --aoi config/aoi.example.geojson --out outputs/buildings.geojson

# 3. Flag farm / industrial storage buildings
python -m landmon.cli flag-storage --aoi config/aoi.example.geojson --out outputs/storage.geojson

# 4. Activity time series + per-date timelines (Sentinel-1 SAR, free)
python -m landmon.cli activity --aoi config/aoi.example.geojson \
    --buildings outputs/storage.geojson --sensor s1 \
    --start 2023-01-01 --end 2024-12-31 --out outputs/activity.geojson

# 5. Dated image chips for the time-slider + popup filmstrip
python -m landmon.cli chips --aoi config/aoi.example.geojson \
    --buildings outputs/activity.geojson --sensor s2 \
    --start 2023-01-01 --end 2024-12-31 --out outputs/chips
```

`outputs/storage.geojson` carries `storage_class`
(`farm_storage` / `industrial_storage` / `possible_storage`) and a `storage_score`.
`outputs/activity.geojson` adds per-building time-series stats (`mean`, `range`,
`trend_per_day`) — a coarse busy/idle proxy, **not** a vehicle count.

## The map viewer (browse map, imagery, tagged locations + activity)

A self-contained web page shows your tagged buildings on a satellite/OS basemap,
**coloured by an activity scale** (blue = idle → red = busy), with a sortable
sidebar, class filters, per-building popups (stats + a dated image filmstrip), and
a colour legend. It runs on the **Python standard library only** — no pip install
needed just to view — and reads whatever GeoJSON exists (`outputs/activity.geojson`
→ `outputs/storage.geojson` → bundled demo data).

```bash
# Runs immediately with bundled demo data — no key, no deps:
python -m landmon.web.server            # -> http://127.0.0.1:8000
# or via the CLI (needs python-dotenv): python -m landmon.cli serve
```

Open `http://127.0.0.1:8000`. With no OS key it shows free **Esri satellite
imagery**; set `OS_API_KEY` to add the OS basemap layer (tiles are proxied through
the server so the key never reaches the browser).

### The activity scale
Each building gets an `activity_index` in 0–1, rendered on a blue→green→yellow→
orange→red ramp (legend in the sidebar). If your data already has `activity_index`
it's used directly; otherwise the server derives one from the Sentinel-1 time-series
stats (`range` of backscatter + positive `trend_per_day` = busier) and falls back to
`storage_score`. It's a **relative, comparative** scale across the sites shown — a
screening signal, not a calibrated occupancy measure.

### Time-slider (animate activity + imagery over time)
If the data has per-date `timeline`s and/or dated chips, the viewer shows a **time-bar**
at the bottom of the map: a **play/pause** button and a **scrubber**. As the date moves,
every building **recolours by its activity on that date** and its **dated image chip is
overlaid on the map**, so you watch the whole AOI change over time. Toggle "imagery
chips" to show colour-only. Each building's **popup has an activity-over-time sparkline**
with a marker that tracks the slider. The bundled demo data includes 2 years of quarterly
timelines + chips, so this works immediately with no key. (The activity coloring is a
**relative** screening signal across the sites/dates shown — see the research report.)

### Dated image chips (the "range of timed images")
`landmon chips` (or `pipeline --chips`) writes one image per building per acquisition
date to `outputs/chips/<id>/<date>.png`; the viewer lists them via `/api/chips/<id>` for
both the time-slider overlays and the popup filmstrip. Choose imagery with `--mode`:
**`rgb`** = true-colour Sentinel-2 (photographic, default), `ndvi` = vegetation,
`sar` = Sentinel-1 radar. Regenerate the demo set with
`python scripts/make_demo_timeseries.py`.

### Viewing over Tailscale
The server binds to `127.0.0.1` by default. Two ways to reach it from your other
devices on the tailnet:

```bash
# Recommended — Tailscale reverse-proxies localhost over HTTPS within your tailnet:
tailscale serve --bg 8000
#   -> https://<your-machine>.<tailnet>.ts.net/   (private to your tailnet)
#   stop sharing with:  tailscale serve --https=443 off

# Or bind to the tailnet interface directly and hit the MagicDNS name / 100.x IP:
python -m landmon.web.server --host 0.0.0.0 --port 8000
#   -> http://<your-machine>:8000   (reachable by any tailnet device)
```

Prefer `tailscale serve` (keeps the app on localhost, adds tailnet-only HTTPS).
Only use `tailscale funnel` if you deliberately want it on the public internet —
not recommended for this. Keep `--host 127.0.0.1`/`tailscale serve` unless you
specifically need raw-interface binding, since the viewer has no auth of its own.

## How "flag storage buildings" works

`buildings.py` scores each OS footprint from three evidence sources (see the module
docstring): OS use/description attributes (when present), geometry (large + simple
rectangular = shed/barn), and rural context (few neighbours = on a farm, not a
village). Thresholds live in `StorageConfig` — tune them for your area, then
**manually review** flagged sites. These are screening heuristics, not ground truth.

## Going to paid sub-metre imagery (when you need real activity)

For sites worth a closer look, buy archive or task new captures at 30–50 cm from
Planet / Maxar / Airbus (directly or via aggregators UP42 / SkyWatch / Apollo
Mapping). Keep the same AOIs/footprints; run vehicle detection or manual counts
across dated captures. For a free first look at past high-res imagery, use
**Esri World Imagery Wayback** and **Google Earth Pro** historical imagery.
Costs, providers and methods are in the research report.

## Legal / ethical

OS Premium data and commercial imagery are licensed — fine for internal analysis,
check terms before redistributing. Monitoring **land and buildings** for land-use,
planning, agricultural or due-diligence purposes is legitimate; at these resolutions
you cannot identify individuals. Keep the purpose to land/structure use. Details in
the research report.

## Status

This is a working scaffold. The free-tier path (OS NGD + Planetary Computer) is
designed to run once you add an OS API key and install the geospatial deps; it has
**not** been executed end-to-end in this environment (no key/network), and OS NGD
collection IDs/attribute names should be confirmed live via `landmon.cli collections`.
