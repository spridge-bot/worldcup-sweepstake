"""Turn a satellite time series into per-building activity metrics.

Given a building footprint and a stacked time series (NDVI from Sentinel-2 or
VV/VH backscatter from Sentinel-1), we summarise each date to a single value over
the footprint (and optionally a surrounding buffer), producing a timeline you can
plot and threshold.

Caveat (see research-report.md): at ~10 m these are *proxies*. They show change
and relative busy/idle trends, not vehicle counts. Use for screening; confirm with
sub-metre imagery before drawing firm conclusions.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

from .aoi import BNG


def _footprint_mask_series(data: xr.DataArray, geom_gdf: gpd.GeoDataFrame):
    """Clip a DataArray to a single footprint geometry (expects projected CRS)."""
    import rioxarray  # noqa: F401  (registers .rio accessor)
    geom = geom_gdf.to_crs(data.rio.crs).geometry.values
    return data.rio.clip(geom, drop=True)


def footprint_timeline(series: xr.DataArray, footprint: gpd.GeoDataFrame,
                       reducer: str = "mean") -> pd.DataFrame:
    """Reduce a time series to one value per date over a building footprint.

    Returns a DataFrame indexed by date with a `value` column.
    """
    clipped = _footprint_mask_series(series, footprint)
    reduced = getattr(clipped, reducer)(dim=("y", "x"), skipna=True)
    df = reduced.to_dataframe(name="value").reset_index()[["time", "value"]]
    df = df.dropna().set_index("time").sort_index()
    return df


def backscatter_db(ds: xr.Dataset, band: str = "vv") -> xr.DataArray:
    """Convert linear Sentinel-1 RTC power to decibels (10*log10)."""
    da = ds[band].where(ds[band] > 0)
    out = 10.0 * np.log10(da)
    out.name = f"{band}_db"
    return out


def activity_summary(timeline: pd.DataFrame) -> dict:
    """Simple summary stats + a crude 'busy vs idle' trend for a footprint."""
    v = timeline["value"]
    if v.empty:
        return {"n": 0}
    # Linear trend (slope per day) as a coarse "increasing activity" signal.
    t = (timeline.index - timeline.index[0]).days.to_numpy(dtype="float64")
    slope = float(np.polyfit(t, v.to_numpy(), 1)[0]) if len(v) > 1 else 0.0
    return {
        "n": int(v.size),
        "mean": float(v.mean()),
        "std": float(v.std()),
        "min": float(v.min()),
        "max": float(v.max()),
        "range": float(v.max() - v.min()),
        "trend_per_day": slope,
    }


def building_timelines(buildings_wgs84: gpd.GeoDataFrame, series: xr.DataArray,
                       reducer: str = "mean") -> list[list[tuple[str, float]]]:
    """Per building, a list of (ISO date, reduced value) over the footprint.

    Aligned to buildings_wgs84.index order; empty list where no data overlaps.
    """
    out: list[list[tuple[str, float]]] = []
    proj = buildings_wgs84.to_crs(BNG)
    for _, row in proj.iterrows():
        one = gpd.GeoDataFrame(geometry=[row.geometry], crs=BNG)
        try:
            df = footprint_timeline(series, one, reducer=reducer)
            pts = [(str(np.datetime_as_string(t, unit="D")), float(v))
                   for t, v in zip(df.index.values, df["value"].values)]
        except Exception:
            pts = []
        out.append(pts)
    return out


def normalise_timelines(timelines: list[list[tuple[str, float]]]
                        ) -> list[list[dict]]:
    """Min-max normalise raw values to activity in 0..1 across ALL buildings/dates
    so colours are comparable. Returns [[{"d":date,"a":activity}, ...], ...]."""
    vals = [v for tl in timelines for _, v in tl]
    if not vals:
        return [[] for _ in timelines]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    return [[{"d": d, "a": round((v - lo) / span, 3)} for d, v in tl]
            for tl in timelines]


def score_buildings(buildings_wgs84: gpd.GeoDataFrame, series: xr.DataArray,
                    reducer: str = "mean") -> gpd.GeoDataFrame:
    """Attach activity summary stats to each building from a time series."""
    rows = []
    proj = buildings_wgs84.to_crs(BNG)
    for idx, row in proj.iterrows():
        one = gpd.GeoDataFrame(geometry=[row.geometry], crs=BNG)
        try:
            tl = footprint_timeline(series, one, reducer=reducer)
            summary = activity_summary(tl)
        except Exception as exc:  # footprint smaller than a pixel, no data, etc.
            summary = {"n": 0, "error": str(exc)}
        summary["building_index"] = idx
        rows.append(summary)
    stats = pd.DataFrame(rows).set_index("building_index")
    return buildings_wgs84.join(stats)
