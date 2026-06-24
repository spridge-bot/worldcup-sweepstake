"""Zero-dependency web viewer for tagged storage buildings + activity scale.

Runs on the Python standard library only, so it starts with just `python` — no
pip install required to *view* results. Serves:

  GET  /                         the Leaflet map page
  GET  /static/*                 page assets
  GET  /api/buildings            GeoJSON of tagged buildings (+ normalised
                                 activity_index in 0..1 if not already present)
  GET  /api/meta                 {os_tiles: bool, count, data_source}
  GET  /tiles/os/<layer>/<z>/<x>/<y>.png
                                 OS Maps raster tiles, proxied so the OS_API_KEY
                                 stays server-side (404 if no key set)
  GET  /chips/<id>/<file>        per-building image chips, if generated
  GET  /api/chips/<id>           list of {date, url} chips for a building

Data source resolution (first that exists):
  --data PATH  ->  outputs/activity.geojson  ->  outputs/storage.geojson
               ->  sample_data/demo_storage.geojson

Designed to sit behind Tailscale — see README "Viewing over Tailscale".
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PKG_ROOT = HERE.parent.parent.parent  # uk-land-monitoring/

OS_TILE_URL = "https://api.os.uk/maps/raster/v1/zxy/{layer}/{z}/{x}/{y}.png"
OS_LAYERS = {"Road", "Outdoor", "Light", "Leisure"}
TILE_RE = re.compile(r"^/tiles/os/([A-Za-z]+)/(\d+)/(\d+)/(\d+)\.png$")
CHIP_LIST_RE = re.compile(r"^/api/chips/([A-Za-z0-9_.-]+)$")
CHIP_FILE_RE = re.compile(r"^/chips/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")


def resolve_data_path(explicit: str | None) -> Path:
    candidates = [explicit] if explicit else []
    candidates += [
        PKG_ROOT / "outputs" / "activity.geojson",
        PKG_ROOT / "outputs" / "storage.geojson",
        PKG_ROOT / "sample_data" / "demo_storage.geojson",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return Path(c)
    raise FileNotFoundError("No buildings GeoJSON found (and no demo data).")


def _num(v):
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


def with_activity_index(fc: dict) -> dict:
    """Ensure every feature has activity_index in 0..1.

    If absent, derive one from the time-series stats (variability `range` and
    `trend_per_day` = busier sites swing more and trend up) or, failing that,
    from storage_score. Normalised across the set so colours are comparable.
    """
    feats = fc.get("features", [])
    have_index = all(_num(f["properties"].get("activity_index")) is not None
                     for f in feats) and feats
    if have_index:
        return fc

    ranges = [_num(f["properties"].get("range")) for f in feats]
    trends = [_num(f["properties"].get("trend_per_day")) for f in feats]
    scores = [_num(f["properties"].get("storage_score")) for f in feats]

    def norm(vals):
        present = [v for v in vals if v is not None]
        if not present:
            return None
        lo, hi = min(present), max(present)
        span = (hi - lo) or 1.0
        return [None if v is None else (v - lo) / span for v in vals]

    n_range, n_trend, n_score = norm(ranges), norm(trends), norm(scores)
    for i, f in enumerate(feats):
        parts = []
        if n_range and n_range[i] is not None:
            parts.append(0.6 * n_range[i])
        if n_trend and n_trend[i] is not None:
            parts.append(0.4 * max(n_trend[i], 0.0))
        if not parts and n_score and n_score[i] is not None:
            parts.append(n_score[i])
        f["properties"]["activity_index"] = round(sum(parts), 4) if parts else 0.0
    return fc


def load_buildings(data_path: Path) -> dict:
    fc = json.loads(Path(data_path).read_text())
    # Guarantee a stable id per feature for chips/linking.
    for i, f in enumerate(fc.get("features", [])):
        props = f.setdefault("properties", {})
        if not props.get("id"):
            props["id"] = props.get("osid") or props.get("name") or f"f{i}"
    return with_activity_index(fc)


class Handler(BaseHTTPRequestHandler):
    server_version = "landmon/0.1"
    data_path: Path = None  # set by run()

    def log_message(self, fmt, *args):  # quieter logs
        pass

    # -- helpers ----------------------------------------------------------- #
    def _send(self, code, body: bytes, ctype: str, cache: int = 0):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", f"public, max-age={cache}")
            self.send_header("Expires", formatdate(timeval=None, usegmt=True))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _file(self, path: Path, ctype: str, cache: int = 3600):
        try:
            self._send(200, path.read_bytes(), ctype, cache)
        except FileNotFoundError:
            self._send(404, b"not found", "text/plain")

    # -- routing ----------------------------------------------------------- #
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "/index.html":
            return self._file(STATIC / "index.html", "text/html; charset=utf-8", 0)
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        if path == "/api/buildings":
            return self._json(load_buildings(self.data_path))
        if path == "/api/meta":
            return self._json({
                "os_tiles": bool(os.environ.get("OS_API_KEY")),
                "data_source": str(self.data_path),
                "count": len(load_buildings(self.data_path).get("features", [])),
            })
        m = TILE_RE.match(path)
        if m:
            return self._proxy_os_tile(*m.groups())
        m = CHIP_LIST_RE.match(path)
        if m:
            return self._list_chips(m.group(1))
        m = CHIP_FILE_RE.match(path)
        if m:
            return self._serve_chip(m.group(1), m.group(2))
        self._send(404, b"not found", "text/plain")

    do_HEAD = do_GET

    # -- handlers ---------------------------------------------------------- #
    def _serve_static(self, rel: str):
        safe = (STATIC / rel).resolve()
        if STATIC not in safe.parents and safe != STATIC:
            return self._send(403, b"forbidden", "text/plain")
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript",
            ".css": "text/css",
            ".png": "image/png",
            ".svg": "image/svg+xml",
        }.get(safe.suffix, "application/octet-stream")
        self._file(safe, ctype)

    def _proxy_os_tile(self, layer, z, x, y):
        key = os.environ.get("OS_API_KEY")
        if not key or layer not in OS_LAYERS:
            return self._send(404, b"no OS key / bad layer", "text/plain")
        url = OS_TILE_URL.format(layer=layer, z=z, x=x, y=y) + f"?key={key}"
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                self._send(200, r.read(), "image/png", cache=86400)
        except Exception:
            self._send(502, b"tile fetch failed", "text/plain")

    def _chip_bases(self) -> list[Path]:
        """Where to look for chips: real outputs first, demo chips as fallback."""
        bases = [PKG_ROOT / "outputs" / "chips"]
        if "sample_data" in str(self.data_path):
            bases.append(PKG_ROOT / "sample_data" / "demo_chips")
        return bases

    def _chip_dir(self, bid: str) -> Path:
        for base in self._chip_bases():
            if (base / bid).is_dir():
                return base / bid
        return self._chip_bases()[0] / bid

    def _list_chips(self, bid: str):
        d = self._chip_dir(bid)
        chips = []
        if d.is_dir():
            paths = sorted(list(d.glob("*.png")) + list(d.glob("*.svg")),
                           key=lambda p: p.stem)
            for p in paths:
                chips.append({"date": p.stem, "url": f"/chips/{bid}/{p.name}"})
        self._json({"id": bid, "chips": chips})

    def _serve_chip(self, bid, fname):
        safe = (self._chip_dir(bid) / fname).resolve()
        allowed = [b.resolve() for b in self._chip_bases()]
        if not any(base in safe.parents for base in allowed):
            return self._send(403, b"forbidden", "text/plain")
        ctype = "image/svg+xml" if safe.suffix == ".svg" else "image/png"
        self._file(safe, ctype)


def run(host: str = "127.0.0.1", port: int = 8000, data: str | None = None):
    Handler.data_path = resolve_data_path(data)
    httpd = ThreadingHTTPServer((host, port), Handler)
    n = len(load_buildings(Handler.data_path).get("features", []))
    os_on = "on" if os.environ.get("OS_API_KEY") else "off (Esri satellite only)"
    print(f"landmon viewer: http://{host}:{port}")
    print(f"  data: {Handler.data_path}  ({n} buildings)")
    print(f"  OS basemap tiles: {os_on}")
    print("  Stop with Ctrl-C. To reach over Tailscale: `tailscale serve 8000`.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m landmon.web.server")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Bind address. Keep 127.0.0.1 behind `tailscale serve`.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--data", help="GeoJSON to display (defaults to outputs/ then demo).")
    a = ap.parse_args(argv)
    run(host=a.host, port=a.port, data=a.data)


if __name__ == "__main__":
    _main()
