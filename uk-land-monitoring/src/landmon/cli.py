"""Command-line entry point.

Examples:
  python -m landmon.cli collections                       # discover OS NGD IDs
  python -m landmon.cli buildings --aoi config/aoi.example.geojson
  python -m landmon.cli flag-storage --aoi config/aoi.example.geojson \
      --out outputs/storage.geojson
  python -m landmon.cli activity --aoi config/aoi.example.geojson \
      --buildings outputs/storage.geojson --start 2023-01-01 --end 2024-12-31
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import aoi as aoi_mod
from . import buildings as bld
from . import os_data

load_dotenv()


def _cmd_collections(args):
    for c in os_data.list_ngd_collections():
        print(f"{c['id']:40s} {c['title']}")


def _cmd_buildings(args):
    a = aoi_mod.load_aoi(args.aoi)
    gdf = os_data.buildings(aoi_mod.bbox(a), max_features=args.max)
    print(f"Fetched {len(gdf)} building features.")
    if args.out:
        gdf.to_file(args.out, driver="GeoJSON")
        print(f"Wrote {args.out}")


def _cmd_flag_storage(args):
    a = aoi_mod.load_aoi(args.aoi)
    gdf = os_data.buildings(aoi_mod.bbox(a), max_features=args.max)
    print(f"Fetched {len(gdf)} buildings; classifying…")
    flagged = bld.flag_storage(gdf)
    counts = flagged["storage_class"].value_counts().to_dict()
    print(f"Flagged {len(flagged)} storage buildings: {counts}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    flagged.to_file(out, driver="GeoJSON")
    print(f"Wrote {out}")


def _build_series(a, sensor, start, end):
    from . import change, sentinel
    if sensor == "s2":
        return sentinel.sentinel2_ndvi_series(a, start, end)
    ds = sentinel.sentinel1_backscatter_series(a, start, end)
    return change.backscatter_db(ds, band="vv")


def _write_activity_geojson(scored, timelines_norm, out: Path):
    """Write GeoJSON by hand so the nested per-date `timeline` array survives
    (GeoJSON drivers flatten/stringify nested properties)."""
    import json

    from shapely.geometry import mapping
    feats = []
    g = scored.to_crs("EPSG:4326")
    for (idx, row), tl in zip(g.iterrows(), timelines_norm):
        props = {k: _py(v) for k, v in row.items() if k != "geometry"}
        props["timeline"] = tl
        props["activity_index"] = round(sum(p["a"] for p in tl) / len(tl), 3) if tl else 0.0
        feats.append({"type": "Feature", "properties": props,
                      "geometry": mapping(row.geometry)})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))


def _py(v):
    """Coerce numpy scalars / NaN to JSON-friendly native Python."""
    import math
    if hasattr(v, "item"):          # numpy scalar
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _cmd_activity(args):
    import geopandas as gpd

    from . import change
    a = aoi_mod.load_aoi(args.aoi)
    buildings_gdf = gpd.read_file(args.buildings)
    print(f"Loaded {len(buildings_gdf)} buildings; building "
          f"{args.sensor} series {args.start}..{args.end}…")
    series = _build_series(a, args.sensor, args.start, args.end)
    scored = change.score_buildings(buildings_gdf, series)
    timelines = change.normalise_timelines(
        change.building_timelines(buildings_gdf, series))
    _write_activity_geojson(scored, timelines, Path(args.out))
    print(f"Wrote per-building activity + timelines to {args.out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="landmon")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("collections", help="List OS NGD collections")
    s.set_defaults(func=_cmd_collections)

    s = sub.add_parser("buildings", help="Fetch OS NGD building footprints")
    s.add_argument("--aoi", required=True)
    s.add_argument("--max", type=int, default=5000)
    s.add_argument("--out")
    s.set_defaults(func=_cmd_buildings)

    s = sub.add_parser("flag-storage", help="Flag farm/industrial storage buildings")
    s.add_argument("--aoi", required=True)
    s.add_argument("--max", type=int, default=5000)
    s.add_argument("--out", default="outputs/storage.geojson")
    s.set_defaults(func=_cmd_flag_storage)

    s = sub.add_parser("activity", help="Per-building satellite activity time series")
    s.add_argument("--aoi", required=True)
    s.add_argument("--buildings", required=True)
    s.add_argument("--sensor", choices=["s1", "s2"], default="s1")
    s.add_argument("--start", required=True)
    s.add_argument("--end", required=True)
    s.add_argument("--out", default="outputs/activity.geojson")
    s.set_defaults(func=_cmd_activity)

    s = sub.add_parser("chips", help="Render per-building dated image chips")
    s.add_argument("--aoi", required=True)
    s.add_argument("--buildings", required=True)
    s.add_argument("--mode", choices=["rgb", "ndvi", "sar"], default="rgb",
                   help="rgb=true-colour Sentinel-2, ndvi=vegetation, sar=Sentinel-1")
    s.add_argument("--start", required=True)
    s.add_argument("--end", required=True)
    s.add_argument("--out", default="outputs/chips")
    s.set_defaults(func=_cmd_chips)

    s = sub.add_parser("pipeline", help="End-to-end: buildings -> flag -> activity -> chips")
    s.add_argument("--aoi", required=True)
    s.add_argument("--start", required=True)
    s.add_argument("--end", required=True)
    s.add_argument("--sensor", choices=["s1", "s2"], default="s1")
    s.add_argument("--max", type=int, default=5000)
    s.add_argument("--outdir", default="outputs")
    s.add_argument("--chips", action="store_true", help="Also render dated image chips")
    s.add_argument("--chip-mode", choices=["rgb", "ndvi", "sar"], default="rgb")
    s.set_defaults(func=_cmd_pipeline)

    s = sub.add_parser("enrich", help="Add location/farm names + lookup links (needs internet)")
    s.add_argument("--in", dest="inp", default="outputs/activity.geojson")
    s.add_argument("--out", default="outputs/activity.geojson")
    s.set_defaults(func=_cmd_enrich)

    s = sub.add_parser("serve", help="Run the web map viewer (zero deps)")
    s.add_argument("--host", default="127.0.0.1",
                   help="Bind address. 127.0.0.1 is safest behind `tailscale serve`.")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--data", help="GeoJSON to display (defaults to outputs/ then demo).")
    s.set_defaults(func=_cmd_serve)
    return p


def _cmd_enrich(args):
    from . import enrich as en
    en.enrich(args.inp, args.out)


def _cmd_pipeline(args):
    """Run the whole chain for an AOI so a single command produces viewer-ready data."""
    import geopandas as gpd

    from . import change, chips
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    a = aoi_mod.load_aoi(args.aoi)

    print("[1/4] Fetching OS NGD buildings…")
    raw = os_data.buildings(aoi_mod.bbox(a), max_features=args.max)
    print(f"      {len(raw)} building footprints")

    print("[2/4] Flagging farm/industrial storage…")
    flagged = bld.flag_storage(raw)
    storage_path = outdir / "storage.geojson"
    flagged.to_file(storage_path, driver="GeoJSON")
    print(f"      {len(flagged)} flagged -> {storage_path}")

    print(f"[3/4] Building {args.sensor} activity time series + timelines…")
    series = _build_series(a, args.sensor, args.start, args.end)
    scored = change.score_buildings(flagged, series)
    timelines = change.normalise_timelines(change.building_timelines(flagged, series))
    activity_path = outdir / "activity.geojson"
    _write_activity_geojson(scored, timelines, activity_path)
    print(f"      -> {activity_path}")

    if args.chips:
        print(f"[4/4] Rendering dated image chips ({args.chip_mode})…")
        cseries, cmap = _build_chip_series(a, args.chip_mode, args.start, args.end)
        flagged_wgs = gpd.read_file(activity_path)
        counts = chips.save_building_chips(cseries, flagged_wgs,
                                           outdir=str(outdir / "chips"),
                                           cmap=cmap or "viridis")
        print(f"      {sum(counts.values())} chips across {len(counts)} buildings")
    else:
        print("[4/4] Skipping chips (pass --chips to enable).")
    print(f"\nDone. View with:  python -m landmon.web.server --data {activity_path}")


def _cmd_serve(args):
    from .web import server
    server.run(host=args.host, port=args.port, data=args.data)


def _build_chip_series(a, mode, start, end):
    """Return (series, cmap) for chip rendering. mode: rgb | ndvi | sar."""
    from . import change, sentinel
    if mode == "rgb":
        return sentinel.sentinel2_rgb_series(a, start, end), None
    if mode == "ndvi":
        return sentinel.sentinel2_ndvi_series(a, start, end), "RdYlGn"
    ds = sentinel.sentinel1_backscatter_series(a, start, end)
    return change.backscatter_db(ds, band="vv"), "viridis"


def _cmd_chips(args):
    import geopandas as gpd

    from . import chips
    a = aoi_mod.load_aoi(args.aoi)
    buildings_gdf = gpd.read_file(args.buildings)
    series, cmap = _build_chip_series(a, args.mode, args.start, args.end)
    counts = chips.save_building_chips(series, buildings_gdf, outdir=args.out,
                                       cmap=cmap or "viridis")
    total = sum(counts.values())
    kind = "true-colour RGB" if args.mode == "rgb" else args.mode
    print(f"Wrote {total} {kind} chips across {len(counts)} buildings into {args.out}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
