"""Ordnance Survey Data Hub access.

Two things we need from OS:
  * OS Maps API  — pre-rendered raster basemap tiles (the detailed OS map look).
  * OS NGD API (Features) — building footprints and land-use polygons as GeoJSON.

Auth: a single OS Data Hub *project API key* (set OS_API_KEY in .env).

NOTE on collection IDs: OS NGD collection IDs are versioned (e.g.
`bld-fts-building-1`) and change over time. Rather than hard-coding, call
`list_ngd_collections()` to discover the current IDs, then pass the one you want
to `ngd_features()`. Sensible defaults are provided but verify them live.
"""
from __future__ import annotations

import os
from typing import Iterator

import geopandas as gpd
import requests

OS_MAPS_WMTS = "https://api.os.uk/maps/raster/v1/zxy/{layer}/{z}/{x}/{y}.png"
OS_NGD_BASE = "https://api.os.uk/features/ngd/ofa/v1"

# Reasonable starting points — confirm against list_ngd_collections().
DEFAULT_BUILDING_COLLECTION = "bld-fts-buildingpart-1"
DEFAULT_LANDUSE_COLLECTION = "lus-fts-site-1"  # OS NGD Land Use sites (verify live)

# OS Maps raster layer styles available on the free/premium plans.
OS_MAP_LAYERS = ["Road", "Outdoor", "Light", "Leisure"]


def _key(api_key: str | None) -> str:
    key = api_key or os.environ.get("OS_API_KEY")
    if not key:
        raise RuntimeError("Set OS_API_KEY in .env or pass api_key=...")
    return key


# --------------------------------------------------------------------------- #
# OS Maps API — raster basemap tiles
# --------------------------------------------------------------------------- #
def os_map_tile_url(layer: str = "Outdoor") -> str:
    """A {z}/{x}/{y} template URL for use as a slippy-map basemap layer.

    Append `?key=...` when actually requesting, or use fetch_tile().
    """
    if layer not in OS_MAP_LAYERS:
        raise ValueError(f"layer must be one of {OS_MAP_LAYERS}")
    return OS_MAPS_WMTS.format(layer=layer, z="{z}", x="{x}", y="{y}")


def fetch_tile(z: int, x: int, y: int, layer: str = "Outdoor",
               api_key: str | None = None) -> bytes:
    """Download a single OS Maps raster tile (PNG bytes)."""
    url = OS_MAPS_WMTS.format(layer=layer, z=z, x=x, y=y)
    r = requests.get(url, params={"key": _key(api_key)}, timeout=30)
    r.raise_for_status()
    return r.content


# --------------------------------------------------------------------------- #
# OS NGD Features API — vector building/land polygons
# --------------------------------------------------------------------------- #
def list_ngd_collections(api_key: str | None = None) -> list[dict]:
    """List available OS NGD collections (id + title). Use to find current IDs."""
    r = requests.get(f"{OS_NGD_BASE}/collections",
                     params={"key": _key(api_key)}, timeout=30)
    r.raise_for_status()
    return [{"id": c["id"], "title": c.get("title", "")}
            for c in r.json().get("collections", [])]


def _ngd_pages(collection: str, bbox: tuple[float, float, float, float],
               api_key: str, cql_filter: str | None,
               max_features: int) -> Iterator[dict]:
    """Yield GeoJSON features, following NGD pagination (limit max 100/page)."""
    url = f"{OS_NGD_BASE}/collections/{collection}/items"
    params = {
        "key": api_key,
        "bbox": ",".join(map(str, bbox)),
        "limit": 100,
    }
    if cql_filter:
        params["filter"] = cql_filter
    fetched = 0
    while url:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        for feat in data.get("features", []):
            yield feat
            fetched += 1
            if fetched >= max_features:
                return
        # Follow the OGC `next` link if present.
        url = next((lk["href"] for lk in data.get("links", [])
                    if lk.get("rel") == "next"), None)
        params = None  # the `next` href already carries query params


def ngd_features(bbox: tuple[float, float, float, float],
                 collection: str = DEFAULT_BUILDING_COLLECTION,
                 cql_filter: str | None = None,
                 max_features: int = 5000,
                 api_key: str | None = None) -> gpd.GeoDataFrame:
    """Fetch OS NGD features in a bbox as a WGS84 GeoDataFrame.

    bbox is (min_lon, min_lat, max_lon, max_lat).
    """
    feats = list(_ngd_pages(collection, bbox, _key(api_key), cql_filter, max_features))
    if not feats:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    return gdf


def buildings(bbox, api_key: str | None = None, **kw) -> gpd.GeoDataFrame:
    """Convenience: fetch building footprints in a bbox."""
    return ngd_features(bbox, collection=DEFAULT_BUILDING_COLLECTION,
                        api_key=api_key, **kw)
