"""Area-of-Interest helpers.

An AOI is just a polygon in WGS84 (EPSG:4326). We keep everything in WGS84 for
APIs (OS bbox queries, STAC search) and reproject to British National Grid
(EPSG:27700) when we need real metres for areas/buffers.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import box, shape

WGS84 = "EPSG:4326"
BNG = "EPSG:27700"  # British National Grid — metres, correct for UK area/length


def load_aoi(path: str | Path) -> gpd.GeoDataFrame:
    """Load an AOI GeoJSON (or any vector file) as a WGS84 GeoDataFrame."""
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    return gdf.to_crs(WGS84)


def aoi_from_bbox(min_lon: float, min_lat: float, max_lon: float, max_lat: float,
                  name: str = "aoi") -> gpd.GeoDataFrame:
    """Build a rectangular AOI from a lon/lat bounding box."""
    return gpd.GeoDataFrame(
        {"name": [name]},
        geometry=[box(min_lon, min_lat, max_lon, max_lat)],
        crs=WGS84,
    )


def bbox(gdf: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    """Return (min_lon, min_lat, max_lon, max_lat) of the AOI in WGS84."""
    return tuple(gdf.to_crs(WGS84).total_bounds)  # type: ignore[return-value]


def to_metres(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproject to British National Grid for correct metre-based geometry ops."""
    return gdf.to_crs(BNG)


def geometry_to_geojson_dict(gdf: gpd.GeoDataFrame):
    """First geometry as a GeoJSON-style dict (for STAC `intersects`)."""
    return shape(gdf.to_crs(WGS84).geometry.iloc[0]).__geo_interface__
