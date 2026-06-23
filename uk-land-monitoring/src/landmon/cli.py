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


def _cmd_activity(args):
    import geopandas as gpd

    from . import change, sentinel
    a = aoi_mod.load_aoi(args.aoi)
    buildings_gdf = gpd.read_file(args.buildings)
    print(f"Loaded {len(buildings_gdf)} buildings; building "
          f"{args.sensor} series {args.start}..{args.end}…")
    if args.sensor == "s2":
        series = sentinel.sentinel2_ndvi_series(a, args.start, args.end)
    else:
        ds = sentinel.sentinel1_backscatter_series(a, args.start, args.end)
        series = change.backscatter_db(ds, band="vv")
    scored = change.score_buildings(buildings_gdf, series)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    scored.to_file(out, driver="GeoJSON")
    print(f"Wrote per-building activity stats to {out}")


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
    s.add_argument("--sensor", choices=["s1", "s2"], default="s2")
    s.add_argument("--start", required=True)
    s.add_argument("--end", required=True)
    s.add_argument("--out", default="outputs/chips")
    s.set_defaults(func=_cmd_chips)

    s = sub.add_parser("serve", help="Run the web map viewer (zero deps)")
    s.add_argument("--host", default="127.0.0.1",
                   help="Bind address. 127.0.0.1 is safest behind `tailscale serve`.")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--data", help="GeoJSON to display (defaults to outputs/ then demo).")
    s.set_defaults(func=_cmd_serve)
    return p


def _cmd_serve(args):
    from .web import server
    server.run(host=args.host, port=args.port, data=args.data)


def _cmd_chips(args):
    import geopandas as gpd

    from . import change, chips, sentinel
    a = aoi_mod.load_aoi(args.aoi)
    buildings_gdf = gpd.read_file(args.buildings)
    if args.sensor == "s2":
        series = sentinel.sentinel2_ndvi_series(a, args.start, args.end)
        cmap = "RdYlGn"
    else:
        ds = sentinel.sentinel1_backscatter_series(a, args.start, args.end)
        series = change.backscatter_db(ds, band="vv")
        cmap = "viridis"
    counts = chips.save_building_chips(series, buildings_gdf, outdir=args.out, cmap=cmap)
    total = sum(counts.values())
    print(f"Wrote {total} chips across {len(counts)} buildings into {args.out}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
