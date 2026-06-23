"""Flag farm-storage / industrial-storage buildings on farms.

There is no single field that says "this is a farm grain store" in free data, so
we combine three evidence sources and score each building footprint:

  1. OS attributes  — if the OS NGD building/site record carries a use/description
     (e.g. agricultural, industrial, warehouse, barn, storage) we trust it most.
  2. Geometry       — agricultural/industrial storage barns are large, low, simple
     rectangular sheds: big footprint, high "rectangularity", few neighbours.
  3. Rural context  — the building sits among farmland, away from dense settlement
     (proxied by building density in a surrounding buffer), optionally confirmed by
     an arable/agricultural land-use layer or by Sentinel-2 vegetation context.

Output: the input buildings GeoDataFrame plus columns:
  area_m2, rectangularity, n_neighbours, is_rural, storage_score,
  storage_class  in {farm_storage, industrial_storage, possible_storage, other}.

These are heuristics meant for *screening* — review flagged sites before acting.
Tune thresholds in StorageConfig for your area.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
from shapely.geometry import MultiPolygon, Polygon

from .aoi import BNG

# Keywords we look for across any free-text/classification OS attribute.
FARM_WORDS = ("agricult", "farm", "barn", "grain", "livestock", "silo", "dutch barn")
INDUSTRIAL_WORDS = ("industr", "warehouse", "storage", "distribution", "depot",
                    "workshop", "garage", "shed", "store", "unit")
# OS attribute names that have historically carried use/description info.
# We probe all of these defensively (schema varies by NGD version).
CANDIDATE_USE_FIELDS = (
    "description", "buildinguse", "oslanduse", "oslandusetiera", "oslandusetierb",
    "primaryuse", "use", "theme", "buildingtheme", "primarysiteclassification",
    "landusetiera", "landusetierb",
)


@dataclass
class StorageConfig:
    min_area_m2: float = 150.0           # storage barns are large
    big_area_m2: float = 400.0           # very likely a shed/warehouse if this big
    min_rectangularity: float = 0.80     # simple rectangular footprint
    neighbour_radius_m: float = 150.0    # for the "isolated / rural" test
    max_neighbours_rural: int = 8        # few near neighbours => rural/farm
    score_threshold: float = 0.5         # >= this => flagged as storage
    farm_words: tuple = field(default_factory=lambda: FARM_WORDS)
    industrial_words: tuple = field(default_factory=lambda: INDUSTRIAL_WORDS)


def _rectangularity(geom: Polygon | MultiPolygon) -> float:
    """area / area(minimum rotated rectangle). 1.0 = perfect rectangle."""
    if geom.is_empty or geom.area == 0:
        return 0.0
    mrr = geom.minimum_rotated_rectangle
    if mrr.area == 0:
        return 0.0
    return float(geom.area / mrr.area)


def _gather_use_text(row) -> str:
    """Concatenate any present OS use/description attributes, lowercased."""
    parts = []
    for fld in CANDIDATE_USE_FIELDS:
        val = row.get(fld)
        if isinstance(val, str) and val.strip():
            parts.append(val.lower())
    return " | ".join(parts)


def classify(buildings_wgs84: gpd.GeoDataFrame,
             config: StorageConfig | None = None) -> gpd.GeoDataFrame:
    """Score and label buildings as farm/industrial storage. Input in WGS84."""
    cfg = config or StorageConfig()
    if buildings_wgs84.empty:
        return buildings_wgs84.assign(storage_class="other", storage_score=0.0)

    g = buildings_wgs84.to_crs(BNG).copy()  # metres for area/distance
    g["area_m2"] = g.geometry.area
    g["rectangularity"] = g.geometry.apply(_rectangularity)

    # Neighbour count within radius (rural/isolation proxy), via centroid join.
    cent = g.copy()
    cent["geometry"] = g.geometry.centroid
    buffered = cent.copy()
    buffered["geometry"] = cent.geometry.buffer(cfg.neighbour_radius_m)
    joined = gpd.sjoin(cent[["geometry"]], buffered[["geometry"]],
                       predicate="within", how="left")
    counts = joined.groupby(joined.index).size() - 1  # exclude self
    g["n_neighbours"] = counts.reindex(g.index).fillna(0).astype(int)
    g["is_rural"] = g["n_neighbours"] <= cfg.max_neighbours_rural

    scores, classes = [], []
    for _, row in g.iterrows():
        use_text = _gather_use_text(row)
        farm_hit = any(w in use_text for w in cfg.farm_words)
        ind_hit = any(w in use_text for w in cfg.industrial_words)

        score = 0.0
        # Geometry: big + rectangular looks like a shed/barn.
        if row["area_m2"] >= cfg.min_area_m2:
            score += 0.25
        if row["area_m2"] >= cfg.big_area_m2:
            score += 0.15
        if row["rectangularity"] >= cfg.min_rectangularity:
            score += 0.20
        # Context: rural / few neighbours => more likely a farm building.
        if row["is_rural"]:
            score += 0.20
        # Attribute evidence (strongest signal when present).
        if farm_hit:
            score += 0.35
        if ind_hit:
            score += 0.25

        score = min(score, 1.0)
        scores.append(score)

        # Label. Prefer explicit attribute evidence; else fall back to geometry+context.
        if score < cfg.score_threshold:
            classes.append("other")
        elif farm_hit and not ind_hit:
            classes.append("farm_storage")
        elif ind_hit and not farm_hit:
            classes.append("industrial_storage")
        elif farm_hit and ind_hit:
            classes.append("industrial_storage")  # industrial unit on a farm
        else:
            # No attribute hit but geometry/context say "big rural shed".
            classes.append("farm_storage" if row["is_rural"] else "possible_storage")

    g["storage_score"] = scores
    g["storage_class"] = classes
    return g.to_crs(buildings_wgs84.crs)


def flag_storage(buildings_wgs84: gpd.GeoDataFrame,
                 config: StorageConfig | None = None) -> gpd.GeoDataFrame:
    """Return only the buildings flagged as farm/industrial storage."""
    classified = classify(buildings_wgs84, config)
    keep = classified["storage_class"].isin(
        ["farm_storage", "industrial_storage", "possible_storage"])
    return classified[keep].sort_values("storage_score", ascending=False)
