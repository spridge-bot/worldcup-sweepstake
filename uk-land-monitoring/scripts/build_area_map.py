#!/usr/bin/env python3
"""Build a standalone aerial-map HTML centred on a point, with a draggable
coordinate-picker pin. Satellite tiles load in the viewer's browser (no server,
no API key). Use it to look at a real area and read off a precise lat/long.

Usage:
  python scripts/build_area_map.py --lat 51.94 --lon -1.10 --zoom 14 \
      --label "≈ OX27 7JE (estimate)" --out outputs/ox27_map.html
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "src" / "landmon" / "web" / "static" / "vendor"

TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Aerial map — {label}</title>
<style>
{leaflet_css}
html,body{{margin:0;height:100%}} #map{{position:absolute;inset:0}}
#banner{{position:absolute;z-index:1000;top:8px;left:50%;transform:translateX(-50%);
  background:rgba(20,24,31,.92);color:#e6e9ee;padding:8px 12px;border-radius:8px;
  font:13px/1.4 system-ui,sans-serif;max-width:92%;box-shadow:0 1px 8px rgba(0,0,0,.4)}}
#banner b{{color:#7ab8ff}} #coord{{font-variant-numeric:tabular-nums}}
.leaflet-popup-content{{font:12px system-ui,sans-serif}}
</style></head>
<body>
<div id="banner">Real satellite imagery of <b>{label}</b>. Drag the pin to your
building — its coordinates show here: <span id="coord">{lat:.5f}, {lon:.5f}</span>.
Send me that to place the auto-tagged version exactly.</div>
<div id="map"></div>
<script>
{leaflet_js}
</script>
<script>
const map = L.map('map').setView([{lat}, {lon}], {zoom});
const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
  {{maxZoom:19, attribution:'Imagery &copy; Esri, Maxar, Earthstar Geographics'}}).addTo(map);
const osm = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{maxZoom:19, attribution:'&copy; OpenStreetMap'}});
L.control.layers({{'Satellite':sat,'Map':osm}},{{}},{{collapsed:false}}).addTo(map);

const marker = L.marker([{lat}, {lon}], {{draggable:true}}).addTo(map);
function show(ll){{
  const t = ll.lat.toFixed(5)+', '+ll.lng.toFixed(5);
  document.getElementById('coord').textContent = t;
  marker.bindPopup('<b>'+t+'</b><br>drag me onto your building').openPopup();
}}
marker.on('dragend', e => show(e.target.getLatLng()));
map.on('click', e => {{ marker.setLatLng(e.latlng); show(e.latlng); }});
show(marker.getLatLng());
</script>
</body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--zoom", type=int, default=14)
    ap.add_argument("--label", default="your area")
    ap.add_argument("--out", default="outputs/area_map.html")
    a = ap.parse_args(argv)
    html = TEMPLATE.format(
        label=a.label, lat=a.lat, lon=a.lon, zoom=a.zoom,
        leaflet_css=(VENDOR / "leaflet.css").read_text(),
        leaflet_js=(VENDOR / "leaflet.js").read_text(),
    )
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB) centred on {a.lat},{a.lon}")


if __name__ == "__main__":
    main()
