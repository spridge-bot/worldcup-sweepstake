"""Render per-building, per-date image chips for the web viewer's filmstrip.

For each building footprint we clip the satellite time series to a small buffer
around it and save one PNG per acquisition date to:

    outputs/chips/<building_id>/<YYYY-MM-DD>.png

The viewer's `/api/chips/<id>` endpoint then lists these so you can scrub a
"range of different timed satellite images" for each tagged location.

Single-band input (NDVI or SAR dB) is rendered with a colormap; pass a Dataset
with red/green/blue bands for true-colour chips. Requires the geospatial deps
(matplotlib, rioxarray) — see requirements.txt.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np

from .aoi import BNG


def _norm(a: np.ndarray, lo=None, hi=None) -> np.ndarray:
    a = a.astype("float32")
    if np.all(np.isnan(a)):
        return np.zeros_like(a)
    lo = np.nanpercentile(a, 2) if lo is None else lo
    hi = np.nanpercentile(a, 98) if hi is None else hi
    if hi - lo == 0:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0, 1)


def _is_rgb(series) -> bool:
    """True if `series` is a Dataset carrying red/green/blue bands."""
    return hasattr(series, "data_vars") and {"red", "green", "blue"} <= set(series.data_vars)


def _rgb_frame(frame) -> np.ndarray:
    """Stack red/green/blue (each percentile-stretched) into an HxWx3 array."""
    chans = [_norm(frame[b].to_numpy()) for b in ("red", "green", "blue")]
    rgb = np.dstack(chans)
    return np.nan_to_num(rgb, nan=0.0)


def save_building_chips(series, buildings_wgs84: gpd.GeoDataFrame,
                        outdir: str | Path = "outputs/chips",
                        buffer_m: float = 60.0, cmap: str = "viridis",
                        id_col: str = "id") -> dict[str, int]:
    """Write one PNG per (building, date). Returns {building_id: n_chips}.

    `series` may be a single-band DataArray (rendered with `cmap`) or a Dataset
    with red/green/blue bands (rendered as true colour, photographic).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rioxarray  # noqa: F401  (registers .rio)

    outdir = Path(outdir)
    written: dict[str, int] = {}
    proj = buildings_wgs84.to_crs(BNG)
    rgb_mode = _is_rgb(series)

    for idx, row in proj.iterrows():
        bid = str(row.get(id_col) or row.get("name") or idx)
        geom = gpd.GeoDataFrame(geometry=[row.geometry.buffer(buffer_m)], crs=BNG)
        try:
            clipped = series.rio.clip(geom.to_crs(series.rio.crs).geometry.values,
                                      drop=True)
        except Exception:
            written[bid] = 0
            continue

        dest = outdir / bid
        dest.mkdir(parents=True, exist_ok=True)
        n = 0
        for t in clipped["time"].values:
            frame = clipped.sel(time=t)
            if rgb_mode:
                img = _rgb_frame(frame)
                empty = not np.any(img)
            else:
                arr = frame.to_numpy() if frame.ndim == 2 else frame.to_numpy()[0]
                empty = np.isnan(arr).all()
                img = _norm(arr)
            if empty:
                continue
            date = str(np.datetime_as_string(t, unit="D"))
            fig, ax = plt.subplots(figsize=(2, 2), dpi=64)
            ax.imshow(img) if rgb_mode else ax.imshow(img, cmap=cmap)
            ax.set_axis_off()
            fig.subplots_adjust(0, 0, 1, 1)
            fig.savefig(dest / f"{date}.png", bbox_inches="tight", pad_inches=0)
            plt.close(fig)
            n += 1
        written[bid] = n
    return written
