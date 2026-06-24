#!/usr/bin/env python3
"""Build a single self-contained dashboard HTML you can open with no server.

Inlines the buildings GeoJSON, the CSS, the app JS, and every image chip (as
base64 data URIs) into one .html. Leaflet and the satellite basemap still load
from their CDNs, so the file needs internet to render the map tiles — but no
Python, no local server. Great for sharing a snapshot (e.g. open it on a phone).

Usage:
  python scripts/build_static.py [--data PATH] [--chips DIR] [--out FILE]

Defaults to the bundled demo data, writing outputs/dashboard_demo.html.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "landmon" / "web" / "static"


def _chip_data_uri(path: Path) -> str:
    raw = path.read_bytes()
    mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def collect_chips(feature_ids, chip_dirs) -> dict:
    chips = {}
    for fid in feature_ids:
        found = []
        for base in chip_dirs:
            d = base / fid
            if d.is_dir():
                for p in sorted(list(d.glob("*.svg")) + list(d.glob("*.png")),
                                key=lambda x: x.stem):
                    found.append({"date": p.stem, "url": _chip_data_uri(p)})
                break
        chips[fid] = found
    return chips


def build(data_path: Path, chip_dirs, out_path: Path) -> Path:
    fc = json.loads(data_path.read_text())
    for i, f in enumerate(fc.get("features", [])):
        f.setdefault("properties", {}).setdefault("id", f["properties"].get("name") or f"f{i}")
    ids = [f["properties"]["id"] for f in fc["features"]]
    chips = collect_chips(ids, chip_dirs)

    css = (STATIC / "style.css").read_text()
    appjs = (STATIC / "app.js").read_text()
    leaflet_css = (STATIC / "vendor" / "leaflet.css").read_text()
    leaflet_js = (STATIC / "vendor" / "leaflet.js").read_text()
    html = (STATIC / "index.html").read_text()

    # Inline EVERYTHING (Leaflet + our CSS/JS + data) so the file has no external
    # script/style deps — only the map tiles load from the web. This is what makes
    # it open correctly from a local file on a phone.
    head_inject = f"<style>\n{leaflet_css}\n{css}\n</style>"
    html = html.replace('<link rel="stylesheet" href="/static/vendor/leaflet.css" />', "")
    html = html.replace('<link rel="stylesheet" href="/static/style.css" />', head_inject)

    data_script = (
        "<script>\n"
        "window.__STATIC__ = true;\n"
        f"window.__BUILDINGS__ = {json.dumps(fc)};\n"
        f"window.__CHIPS__ = {json.dumps(chips)};\n"
        "</script>"
    )
    html = html.replace('<script src="/static/vendor/leaflet.js"></script>',
                        f"<script>\n{leaflet_js}\n</script>")
    html = html.replace('<script src="/static/app.js"></script>',
                        data_script + f"\n<script>\n{appjs}\n</script>")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    n_chips = sum(len(v) for v in chips.values())
    print(f"Wrote {out_path} ({len(ids)} buildings, {n_chips} chips, "
          f"{out_path.stat().st_size // 1024} KB)")
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "sample_data" / "demo_storage.geojson"))
    ap.add_argument("--chips", action="append",
                    help="Chip dir(s) to search (default: outputs/chips then demo).")
    ap.add_argument("--out", default=str(ROOT / "outputs" / "dashboard_demo.html"))
    a = ap.parse_args(argv)
    chip_dirs = ([Path(c) for c in a.chips] if a.chips
                 else [ROOT / "outputs" / "chips", ROOT / "sample_data" / "demo_chips"])
    build(Path(a.data), chip_dirs, Path(a.out))


if __name__ == "__main__":
    main()
