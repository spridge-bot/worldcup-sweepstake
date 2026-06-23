# UK Land Monitoring — OS maps + satellite imagery for rural building activity

A toolkit + research write-up for reading detailed **Ordnance Survey** maps and
**satellite imagery**, flagging **farm-storage / industrial-storage buildings on
farmland** (Oxfordshire), and screening **how actively used** they are over time.

> **Read first:** [`docs/research-report.md`](docs/research-report.md) — the full
> research on data sources, resolution/cost/revisit trade-offs, feasibility, and
> legal/licensing notes. The one-line version is below.

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
  cli.py        Command-line pipeline
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

```bash
# 1. Discover current OS NGD collection IDs (they're versioned)
python -m landmon.cli collections

# 2. Fetch building footprints in the AOI
python -m landmon.cli buildings --aoi config/aoi.example.geojson --out outputs/buildings.geojson

# 3. Flag farm / industrial storage buildings
python -m landmon.cli flag-storage --aoi config/aoi.example.geojson --out outputs/storage.geojson

# 4. Screen activity over time (Sentinel-1 SAR backscatter trend, free)
python -m landmon.cli activity --aoi config/aoi.example.geojson \
    --buildings outputs/storage.geojson --sensor s1 \
    --start 2023-01-01 --end 2024-12-31 --out outputs/activity.geojson
```

`outputs/storage.geojson` carries `storage_class`
(`farm_storage` / `industrial_storage` / `possible_storage`) and a `storage_score`.
`outputs/activity.geojson` adds per-building time-series stats (`mean`, `range`,
`trend_per_day`) — a coarse busy/idle proxy, **not** a vehicle count.

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
