# UK OS Maps + Satellite Imagery for Monitoring Rural Building Activity — Research Report

**Question:** Can we read detailed UK Ordnance Survey (OS) maps and high‑definition
satellite imagery, and use a *time series* of satellite images to track how actively
used farm buildings / industrial garages on farmland or surrounded by arable land in
Oxfordshire are?

**Short answer:** Yes to mapping and imagery. "Tracking how actively used a building is"
is feasible but the method depends entirely on what you can spend, because of a hard
three‑way trade‑off between **spatial resolution**, **revisit frequency**, and **cost**.

- **Free imagery** (Sentinel‑2 at 10 m, Sentinel‑1 radar) → you can detect *change* over
  weeks/months/years (new structures, expanding hardstanding/yards, vehicle *clusters* as
  blobs, disturbance of surrounding crops) and characterise the **surrounding arable land**
  well. You **cannot** count individual cars/vans or see day‑to‑day comings and goings —
  most vehicles are smaller than a single 10 m pixel.
- **Commercial sub‑metre imagery** (Planet SkySat 50 cm, Maxar/Vantor 30 cm, Airbus
  Pléiades Neo 30 cm) → you *can* count vehicles, see open doors/yard clutter, and measure
  activity at a specific building, but you pay per km² or per subscription, and high‑revisit
  "tasking" has minimum order sizes.

A practical programme combines both: free data for wide, cheap, longitudinal screening,
then targeted paid captures only on the handful of sites that look interesting.

---

## 1. Mapping & vector data — Ordnance Survey

The **OS Data Hub** (https://osdatahub.os.uk) is the single front door to OS data, offering
free ("OS OpenData"), and Premium products. Three things matter for this project:

| Product | What it gives you | Tier |
|---|---|---|
| **OS Maps API** | Pre‑rendered raster basemap tiles (Leisure/Outdoor, Road, Light, Greyscale) as a slippy/WMTS layer — the "detailed OS map" look | Free OpenData + Premium styles |
| **OS NGD API – Features** | The **National Geographic Database** as queryable GeoJSON vectors: building footprints, land use/land cover, sites, structures, water, etc. This is how you get exact building polygons to monitor | Premium (free monthly credit) |
| **OS NGD API – Tiles / OS Vector Tile API** | Vector tiles for custom cartography | Premium |

Key points:
- OS's newer **NGD Features API** replaces the old Features API: OGC‑compliant, returns
  GeoJSON, better filtering (CQL), themes such as **Buildings** (`bld-*`), **Land** (`lnd-*`),
  **Structures** (`str-*`), **Sites** (`gnm-*`/`sit-*`). Collection IDs are versioned and
  change over time, so query the live `/collections` endpoint rather than hard‑coding them.
- Access uses a **project API key** from the Data Hub. Premium APIs come with a recurring
  **free credit allowance** each month; you only pay if you exceed it. Public‑sector users
  get much of this free under the **Public Sector Geospatial Agreement (PSGA)**.
- Official Python helper: **`osdatahub`** (`pip install osdatahub`), plus the
  `OS-Data-Hub-API-Demos` repo for worked examples.

For our purpose, OS data is the **base layer**: it lets you precisely locate and outline
each candidate farm building / garage, find parcels and land‑use context, and snap your
imagery analysis to real footprints — rather than guessing where a building is from pixels.

### OS / UK aerial photography (the "HD" map‑grade imagery)
OS itself does not sell raw orthophotos through the free Data Hub tiers, but very‑high‑res
aerial photography of Great Britain (12.5–25 cm) is available through **Aerial Photography
for Great Britain (APGB)** and suppliers **Getmapping** and **Bluesky** (Getmapping imagery
also underpins parts of Esri's World Imagery basemap). This is **excellent spatial detail**
but it is flown occasionally (roughly annually in many areas), so it is **not a dense time
series** — better for a precise "what is here" snapshot than for "how often is it used".

---

## 2. Free satellite imagery — the workhorse for screening

| Source | Resolution | Revisit | Cost | Best for |
|---|---|---|---|---|
| **Sentinel‑2** (optical, 13 bands) | 10 m (visible/NIR), 20 m (red‑edge/SWIR) | ~5 days (2 sats) | Free | Surrounding crop cycles (NDVI), seasonal land use, coarse change, big yard/vehicle *clusters* |
| **Sentinel‑1** (C‑band SAR radar) | ~10–20 m | ~6–12 days | Free | All‑weather, day/night; new construction, hardstanding, metal/vehicle backscatter change |
| **Landsat 8/9** | 30 m (15 m pan), + **thermal** | ~8 days combined | Free | Long archive (back to 1980s), thermal proxy |

**How to access the free archives (all free, pick one):**
- **Microsoft Planetary Computer** — STAC API + signed asset URLs, no cost; easiest for
  Python/`pystac-client`/`odc-stac`. *(This scaffold uses it for the runnable demo.)*
- **Copernicus Data Space Ecosystem** — official ESA portal, STAC + Sentinel Hub APIs.
- **AWS Open Data / Earth Search** — Sentinel‑2 COGs on S3.
- **Google Earth Engine** — planetary‑scale time‑series analysis in the cloud (free for
  research/non‑commercial; great for change‑detection at scale).

**What free data realistically tells you about a building's "activity":**
1. **Surrounding land** (strong signal): Sentinel‑2 NDVI time series shows the cropping
   calendar of the arable land around the building — ploughing, growth, harvest, bare soil,
   tracks/compaction. Unusual disturbance (a worn access track, an expanding yard, soil
   scarring) is visible and is itself an activity proxy.
2. **The building & its yard** (weak‑to‑moderate signal): A 10 m pixel can show a *change*
   in the bright/built‑up footprint — a new roof, a new concrete pad, a yard that fills with
   stuff. Sentinel‑1 radar backscatter rises when metal objects (vehicles, machinery,
   containers) accumulate on a previously empty hardstanding, so a **backscatter time series
   over the footprint** can hint at "busy vs idle" periods, all‑weather.
3. **Thermal proxy** (weak, coarse): Landsat thermal / research using Sentinel‑2 **B12 SWIR**
   has been used to infer indoor activity from heat signatures — but at 30–100 m this only
   works for larger/warmer buildings, not a single small garage.

So: free data is genuinely useful for **longitudinal screening across many sites** and for
**characterising the farmland context**, but it will not, on its own, tell you "three vans
arrived on Tuesday".

---

## 3. Commercial sub‑metre imagery — needed to actually measure activity

To **count vehicles, see open doors, distinguish a working yard from an idle one**, you need
roughly **≤ 50 cm** ground resolution. The main providers:

| Provider | Resolution | Revisit | Notes |
|---|---|---|---|
| **Planet — SkySat** | ~50 cm | Up to **sub‑daily** (taskable) | 15 SkySats; best for repeated same‑site captures; also PlanetScope 3 m daily for context |
| **Maxar / Vantor — WorldView Legion** | **30 cm** | Up to **15×/day** over priority areas | Highest detail + revisit; best archive depth |
| **Airbus — Pléiades Neo** | **30 cm** | Daily‑ish (taskable) | Strong tasking & fast delivery |

**Indicative 2025 pricing** (varies by provider/area/licence):
- **Archive** very‑high‑res (<1 m): roughly **$15–$30 per km²**.
- **New tasking** (<1 m): roughly **$40–$60 per km²**, with **minimum order areas**
  (commonly ~25 km² per tasking order, so a single garage is "small" but you still pay the
  minimum).
- **Subscriptions**: from **under ~$30k/year** for higher‑volume access.

A farm building + yard is a tiny area, so **archive imagery at several past dates is cheap
per site** — the practical constraint is the *minimum order* and *whether the archive
happened to capture your site on useful dates*. **Tasking** (commissioning new captures on a
schedule) is what gives a true high‑cadence "activity" time series, and is the costlier path.

**Aggregators / easier buying:** **UP42**, **SkyWatch**, **Apollo Mapping**, **LandInfo**,
**Arlula** let you search archives and buy across providers via one API/account — usually the
simplest way to pull "the same 1 km² on 12 different past dates".

### Free retrospective high‑res viewers (manual, but $0)
For a quick first look at *past* high‑res imagery of a specific site, before spending anything:
- **Esri World Imagery Wayback** — 150+ archived versions of the World Imagery basemap over
  ~8 years; swipe/animate between dates.
- **Google Earth Pro** — "historical imagery" time slider; often several captures per year in
  populated areas, fewer in deep countryside.
- **Google Earth Engine** also exposes some high‑res basemap history.

These are perfect for eyeballing "did this yard look busy in 2019 vs 2023" without an imagery
budget, and for deciding which sites justify paid captures.

---

## 4. Detecting "activity" — methods, by data tier

| Signal you want | Free data approach | Paid data approach |
|---|---|---|
| New building / extension / new hardstanding | Sentinel‑1 SAR change detection; Sentinel‑2 before/after | Obvious in 30–50 cm imagery |
| Vehicles present / count | Not reliable (sub‑pixel) — only clusters as bright blobs | Object detection on 30–50 cm imagery (cars ~2 px) |
| Yard "busyness" over time | Sentinel‑1 backscatter time series over footprint (proxy) | Visual/ML count across dated captures |
| Surrounding crop activity, access tracks | **Sentinel‑2 NDVI time series** (strong) | Same, plus visible ruts/wear |
| Indoor/heat activity | Landsat thermal proxy (coarse); B12 SWIR research method | Commercial thermal (e.g. SatVu ~3.5 m thermal) |

**Recommended analytical pipeline (and what this repo scaffolds):**
1. **Locate & outline** every candidate building with OS NGD building footprints + OS Maps
   basemap; define an Area of Interest (AOI) per site or per region.
2. **Free longitudinal screen:** build Sentinel‑2 (NDVI) and Sentinel‑1 (VV/VH backscatter)
   time series over each footprint and its surrounding land; flag sites with rising
   backscatter, expanding bright footprint, or anomalous surrounding disturbance.
3. **Free retrospective check:** eyeball flagged sites in Esri Wayback / Google Earth Pro.
4. **Targeted paid captures:** for the shortlist, buy **archive** sub‑metre imagery at several
   dates (cheap per site) or **task** new captures for a true activity cadence; run vehicle
   detection / manual counts.
5. (Optional) thermal for occupancy/heat signals.

This keeps spend proportional to interest: free + manual for the many, paid only for the few.

---

## 5. Legal, licensing & ethical notes

- **OS data licensing:** OS OpenData is under the **Open Government Licence (OGL)**; Premium
  NGD/OS Maps data is under **OS Data Hub terms** (and **PSGA** for public sector). You
  generally **may not redistribute** Premium data or derived data outside licence terms —
  fine for internal analysis, check terms before publishing maps/derived datasets. Commercial
  use needs a commercial licence/plan.
- **Satellite imagery licensing:** Commercial imagery (Planet/Maxar/Airbus) is **per‑seat /
  per‑use licensed** — you typically cannot publicly republish full‑res scenes; derived
  analytics are usually fine. Sentinel/Landsat are free and open (attribution appreciated).
- **Privacy / GDPR:** Monitoring **land and buildings** for land‑use, planning, agricultural
  or due‑diligence purposes is a normal, legitimate activity (UK councils use exactly this for
  planning enforcement). At these resolutions you **cannot** read number plates or identify
  individuals, so personal‑data risk is low — but if a workflow ever sought to track
  identifiable people, that would raise GDPR/Data Protection Act 2018 obligations and is out
  of scope here. Keep the purpose to **land/structure use**, document a lawful basis if you're
  an organisation, and don't combine with personal data.
- **Lawful basis / use case:** Typical legitimate uses include planning‑enforcement support,
  agricultural/land‑management monitoring, environmental compliance (e.g. waste/illegal
  development), property due diligence, and journalism/research. Use the tooling accordingly.

---

## 6. Recommended stack for this project

- **Mapping/vectors:** OS Data Hub — OS Maps API (raster basemap) + OS NGD Features API
  (building/land polygons), via the `osdatahub` Python package or direct REST.
- **Free imagery & time series:** Microsoft Planetary Computer (Sentinel‑2 L2A, Sentinel‑1
  RTC) via `pystac-client` + `odc-stac` + `rioxarray`/`xarray`; optionally Google Earth Engine
  for large‑area change detection.
- **Analysis:** `numpy`/`xarray` for NDVI & backscatter time series; `geopandas`/`shapely`
  for footprints/AOIs; `matplotlib` for plots/chips.
- **Paid tier (when needed):** UP42 / SkyWatch / provider APIs for archive & tasking of
  sub‑metre imagery; plug into the same AOI definitions.
- **Manual retrospective:** Esri Wayback + Google Earth Pro.

See `../README.md` for setup and the runnable free‑tier demo.

---

## Sources

- [OS Data Hub](https://osdatahub.os.uk/) · [OS Documentation](https://osdatahub.os.uk/docs/ofa/overview) · [`osdatahub` PyPI](https://pypi.org/project/osdatahub/) · [`osdatahub` GitHub](https://github.com/OrdnanceSurvey/osdatahub) · [OS Data Hub API Demos](https://github.com/OrdnanceSurvey/OS-Data-Hub-API-Demos) · [OS Data Hub for public sector](https://www.ordnancesurvey.co.uk/customers/public-sector/os-data-hub-public-sector)
- [Sentinel‑2 in Earth Engine Data Catalog](https://developers.google.com/earth-engine/datasets/catalog/sentinel-2) · [Detecting Changes in Sentinel‑1 Imagery (GEE tutorial)](https://developers.google.com/earth-engine/tutorials/community/detecting-changes-in-sentinel-1-imagery-pt-1)
- [Planet pricing](https://www.planet.com/pricing/) · [Planet high‑resolution / SkySat tasking](https://www.planet.com/products/high-resolution-satellite-imagery/) · [Maxar/Vantor WorldView tasking](https://www.maxar.com/products/satellite-imagery) · [L3Harris high‑res imagery](https://www.l3harris.com/all-capabilities/high-resolution-satellite-imagery)
- [Satellite imagery pricing guide (OnGeo)](https://ongeo-intelligence.com/blog/satellite-imagery-pricing-guide) · [Demystifying satellite data pricing (Geoawesome)](https://geoawesome.com/demystifying-satellite-data-pricing-a-comprehensive-guide/) · [LandInfo pricing](https://landinfo.com/satellite-imagery-pricing/) · [SkyWatch pricing](https://skywatch.com/satellite-imagery-pricing-what-you-need-to-know/) · [UP42 release notes](https://up42.com/release-notes)
- [Esri World Imagery Wayback](https://livingatlas.arcgis.com/wayback/) · [Free historical imagery viewers (GIS Geography)](https://gisgeography.com/free-historical-imagery-viewers/)
- [Heat‑emission signatures of buildings from satellite data (Springer, 2025)](https://link.springer.com/article/10.1007/s12145-025-01926-6) · [Automatic detection of new building construction from Sentinel‑1 (ResearchGate)](https://www.researchgate.net/publication/359958046_Automatic_Detection_of_New_Building_Construction_from_Sentinel-1_Multi-temporal_Imagery)
</invoke>
