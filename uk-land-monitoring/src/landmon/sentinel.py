"""Free satellite time series via Microsoft Planetary Computer (STAC).

No API key required for browsing; the `planetary-computer` package signs asset
URLs so the COGs load over HTTPS. We provide:

  * sentinel2_ndvi_series  — optical, NDVI (crop/vegetation activity, ~10 m).
  * sentinel2_rgb_series   — true-colour red/green/blue (photographic chips, ~10 m).
  * sentinel1_backscatter_series — C-band SAR VV/VH (all-weather, metal/vehicle &
    construction proxy, ~10 m).

Both return an xarray.DataArray/Dataset stacked on a `time` dimension over the AOI,
ready for the metrics in change.py.
"""
from __future__ import annotations

import geopandas as gpd
import planetary_computer as pc
import pystac_client
from odc.stac import load as odc_load

from .aoi import bbox as aoi_bbox

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def _client() -> pystac_client.Client:
    return pystac_client.Client.open(STAC_URL, modifier=pc.sign_inplace)


def _search(collection: str, aoi: gpd.GeoDataFrame, start: str, end: str,
            query: dict | None = None):
    items = _client().search(
        collections=[collection],
        bbox=list(aoi_bbox(aoi)),
        datetime=f"{start}/{end}",
        query=query or {},
    ).item_collection()
    return items


def sentinel2_ndvi_series(aoi: gpd.GeoDataFrame, start: str, end: str,
                          max_cloud: int = 30, resolution: int = 10):
    """NDVI time series (xarray DataArray, dims time,y,x) over the AOI.

    NDVI = (NIR - Red) / (NIR + Red), bands B08 and B04.
    """
    items = _search("sentinel-2-l2a", aoi, start, end,
                    query={"eo:cloud_cover": {"lt": max_cloud}})
    if len(items) == 0:
        raise RuntimeError("No Sentinel-2 scenes for AOI/dates/cloud filter.")
    ds = odc_load(
        items, bands=["B04", "B08", "SCL"],
        bbox=list(aoi_bbox(aoi)), resolution=resolution,
        chunks={}, groupby="solar_day",
    )
    # Mask clouds/shadow using the Scene Classification Layer (SCL).
    # Keep vegetation/soil/water (4,5,6); drop cloud/shadow/snow (3,8,9,10,11).
    good = ds["SCL"].isin([4, 5, 6, 7, 2, 11]) | (ds["SCL"] == 6)
    red, nir = ds["B04"].astype("float32"), ds["B08"].astype("float32")
    ndvi = (nir - red) / (nir + red)
    ndvi = ndvi.where(good)
    ndvi.name = "ndvi"
    return ndvi


def sentinel2_rgb_series(aoi: gpd.GeoDataFrame, start: str, end: str,
                         max_cloud: int = 30, resolution: int = 10):
    """True-colour Sentinel-2 time series Dataset (red/green/blue) over the AOI.

    Bands B04/B03/B02 (10 m). Cloud/shadow masked via SCL. Values are surface
    reflectance (0..~10000); chips.py stretches them for display. Use this for
    photographic-looking image chips/overlays.
    """
    items = _search("sentinel-2-l2a", aoi, start, end,
                    query={"eo:cloud_cover": {"lt": max_cloud}})
    if len(items) == 0:
        raise RuntimeError("No Sentinel-2 scenes for AOI/dates/cloud filter.")
    ds = odc_load(
        items, bands=["B04", "B03", "B02", "SCL"],
        bbox=list(aoi_bbox(aoi)), resolution=resolution,
        chunks={}, groupby="solar_day",
    )
    good = ds["SCL"].isin([2, 4, 5, 6, 7, 11])  # drop cloud/shadow/snow
    rgb = ds[["B04", "B03", "B02"]].where(good)
    return rgb.rename({"B04": "red", "B03": "green", "B02": "blue"})


def sentinel1_backscatter_series(aoi: gpd.GeoDataFrame, start: str, end: str,
                                 resolution: int = 10):
    """Sentinel-1 RTC backscatter (VV, VH) time series Dataset over the AOI.

    Rising backscatter over a hardstanding/yard can indicate accumulating metal
    objects (vehicles, machinery, containers) — an all-weather activity proxy.
    """
    items = _search("sentinel-1-rtc", aoi, start, end)
    if len(items) == 0:
        raise RuntimeError("No Sentinel-1 RTC scenes for AOI/dates.")
    ds = odc_load(
        items, bands=["vv", "vh"],
        bbox=list(aoi_bbox(aoi)), resolution=resolution,
        chunks={}, groupby="solar_day",
    )
    return ds
