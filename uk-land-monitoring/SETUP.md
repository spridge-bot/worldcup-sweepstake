# Setup — real pipeline + example dashboard

This walks from a clean machine to (a) the **example dashboard running on demo data**
(no account, no network) and (b) the **real pipeline** producing live Oxfordshire data.

---

## 0. The fastest path — example dashboard, zero setup

The viewer is pure standard library and ships with demo data, so:

```bash
git clone <repo> && cd worldcup-sweepstake/uk-land-monitoring
python -m landmon.web.server          # open http://127.0.0.1:8000
```

You'll see 7 tagged buildings on satellite imagery, coloured by activity, with the
time-slider, popups (with sparkline charts) and dated chips. This needs **only Python
3.10+** — nothing else. Use it to confirm the dashboard works before wiring real data.

```bash
make demo      # regenerate demo time-series + chips, then serve (same thing)
```

---

## 1. What the real pipeline needs

| Need | Why | Cost |
|---|---|---|
| **Python 3.10+** | runtime | free |
| **The geospatial deps** (`requirements.txt`) | OS vectors + satellite rasters | free |
| **An OS Data Hub API key** | building footprints (OS NGD) + OS basemap | free tier, monthly credit |
| **Internet access** | OS API + Microsoft Planetary Computer (satellite) | free |
| **(optional) Tailscale** | view the dashboard from other devices privately | free |

Microsoft Planetary Computer (the satellite source) needs **no account** — the
`planetary-computer` package signs data URLs for you. So the only credential is the OS key.

### 1a. Install
```bash
cd uk-land-monitoring
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
```
Most deps ship prebuilt wheels (rasterio/pyogrio/pyproj/shapely bundle their own GDAL),
so this is usually a clean `pip install`. If `rasterio`/`odc-stac` fail to build on an
unusual platform, install system GDAL first (`apt-get install gdal-bin libgdal-dev` /
`brew install gdal`) or use the conda-forge builds (`conda install -c conda-forge
geopandas odc-stac rioxarray pystac-client planetary-computer`).

### 1b. Get an OS Data Hub API key
1. Create a free account at <https://osdatahub.os.uk/>.
2. **Create an API project** (Dashboard → API → "Create a new API project").
3. Add the products: **OS NGD API – Features** and **OS Maps API**.
4. Copy the project's **API key** (Project API Key).
5. Put it in `.env`:
   ```bash
   cp .env.example .env
   echo "OS_API_KEY=your_key_here" >> .env      # or edit .env
   ```
The free tier includes a recurring monthly transaction allowance — ample for a few AOIs.
Public-sector users get this under the PSGA.

### 1c. Pick an Area of Interest
Edit `config/aoi.example.geojson` (or make your own) — a polygon in WGS84 lon/lat.
**Start small** (a few km²) to keep API credits and download time low; scale up later.

---

## 2. Run it

```bash
# Confirm the live OS NGD collection IDs (they're versioned)
python -m landmon.cli collections

# One command: buildings -> flag storage -> activity+timelines -> true-colour chips
python -m landmon.cli pipeline --aoi config/aoi.example.geojson \
    --start 2023-01-01 --end 2024-12-31 --sensor s1 --chips --chip-mode rgb

# View it (then share over Tailscale — see README)
python -m landmon.web.server --data outputs/activity.geojson
```

`make pipeline AOI=config/aoi.example.geojson START=2023-01-01 END=2024-12-31` does the
same. Outputs land in `outputs/` (`storage.geojson`, `activity.geojson`, `chips/`), which
the viewer picks up automatically.

### Chip imagery modes
- `--chip-mode rgb`  → true-colour Sentinel-2 (photographic; **default**)
- `--chip-mode ndvi` → vegetation index (crop activity around the building)
- `--chip-mode sar`  → Sentinel-1 radar (all-weather)

### Keep it running + weekly auto-refresh
To leave the dashboard up and refresh the data **once a week** automatically, see
[`deploy/README.md`](deploy/README.md) — it has ready-made macOS (launchd), Linux
(systemd) and cron units. `scripts/refresh.sh` re-runs the pipeline over a rolling
12-month window and swaps results in atomically (a failed run keeps the previous data,
so the dashboard never breaks). The viewer reads the files live, so a refresh updates
it with no restart.

---

## 3. Troubleshooting

| Symptom | Fix |
|---|---|
| `Set OS_API_KEY` error | `.env` missing/empty, or run from the `uk-land-monitoring` dir; `export PYTHONPATH=src` |
| OS NGD 401/403 | key not enabled for **OS NGD API – Features**; re-check the project products |
| Wrong/empty buildings | collection ID changed — run `landmon.cli collections` and set `DEFAULT_BUILDING_COLLECTION` in `os_data.py` |
| "No Sentinel-2/-1 scenes" | widen `--start/--end`, or raise the cloud limit; SAR (`--sensor s1`) is cloud-proof |
| `rasterio`/GDAL build fails | use conda-forge builds, or install system GDAL (see 1a) |
| Chips empty for a building | footprint smaller than a pixel or fully cloud-masked — try `--chip-mode sar` |
| Dashboard loads but no tiles | with no `OS_API_KEY` only Esri satellite shows; that's expected |

---

## 4. Cost & scope reminder

Everything above is **free**: OS free tier + free Sentinel imagery. That gets you
mapping, storage-building flagging, and a **relative** activity signal over time. To
actually **count vehicles / measure fine activity** you need commercial sub-metre imagery
(Planet/Maxar/Airbus) — priced and explained in [`docs/research-report.md`](docs/research-report.md).
