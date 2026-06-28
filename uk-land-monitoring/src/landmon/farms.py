"""Group flagged buildings into farm 'holdings' and estimate their land.

Runs after the pipeline (and ideally after `enrich`, so farm names exist). It:
  * clusters nearby storage buildings into holdings (proxy for one farm),
  * names each from the OSM farm names enrich found (else nearest location),
  * aggregates activity/availability + total footprint per holding,
  * estimates surrounding farmland area from OpenStreetMap (Overpass, needs net),
  * writes outputs/farms.geojson (holding polygons + stats) and tags every
    building with farm_id / farm so the viewer can link them.

Honest note: holdings are spatial clusters, not legal ownership boundaries, and
"surrounding farmland" is nearby OSM land for context — not a title boundary.
Confirm real ownership/extent via the Land Registry links in the viewer.
"""
from __future__ import annotations

import json
from collections import Counter

import geopandas as gpd
import requests
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from .aoi import BNG

OVERPASS = "https://overpass-api.de/api/interpreter"
UA = {"User-Agent": "uk-land-monitoring/0.1 (storage finder)"}


def _clusters(centroids_m, dist=250.0):
    """Union-find clustering: buildings within `dist` metres share a holding."""
    n = len(centroids_m)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    d2 = dist * dist
    for i in range(n):
        xi, yi = centroids_m[i]
        for j in range(i + 1, n):
            xj, yj = centroids_m[j]
            if (xi - xj) ** 2 + (yi - yj) ** 2 <= d2:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _nearby_farmland_ha(centroid_wgs, radius_m=600):
    """Sum OSM farmland/farmyard area (ha) within radius of a holding centroid."""
    lon, lat = centroid_wgs.x, centroid_wgs.y
    q = (f'[out:json][timeout:30];('
         f'way(around:{radius_m},{lat},{lon})["landuse"~"farmland|farmyard|meadow"];'
         f');out geom;')
    try:
        r = requests.post(OVERPASS, data=q, headers=UA, timeout=45)
        r.raise_for_status()
        polys = []
        for el in r.json().get("elements", []):
            g = el.get("geometry") or []
            if len(g) >= 3:
                ring = [(p["lon"], p["lat"]) for p in g]
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                polys.append({"type": "Polygon", "coordinates": [ring]})
        if not polys:
            return None
        gdf = gpd.GeoDataFrame(geometry=[shape(p) for p in polys], crs="EPSG:4326").to_crs(BNG)
        return round(float(gdf.geometry.area.sum()) / 10000.0, 1)
    except Exception:
        return None


def build(in_path: str, out_path: str, cluster_m: float = 250.0,
          land: bool = True) -> int:
    g = gpd.read_file(in_path)
    if g.empty:
        json.dump({"type": "FeatureCollection", "features": []}, open(out_path, "w"))
        return 0
    gm = g.to_crs(BNG)
    cents = [(geom.centroid.x, geom.centroid.y) for geom in gm.geometry]
    clusters = _clusters(cents, cluster_m)

    # tag buildings with farm_id
    farm_id_by_row = {}
    for fid, members in enumerate(clusters):
        for m in members:
            farm_id_by_row[m] = fid

    feats = []
    fc_in = json.loads(open(in_path).read())
    for i, feat in enumerate(fc_in["features"]):
        feat.setdefault("properties", {})["farm_id"] = farm_id_by_row.get(i)

    print(f"Grouping {len(g)} buildings into {len(clusters)} holdings…")
    for fid, members in enumerate(clusters):
        sub = gm.iloc[members]
        # Holding extent = union of building footprints buffered by 40 m.
        hull = unary_union([geom.buffer(40) for geom in sub.geometry])
        hull_wgs = gpd.GeoSeries([hull], crs=BNG).to_crs("EPSG:4326").iloc[0]
        cent_wgs = gpd.GeoSeries([hull.centroid], crs=BNG).to_crs("EPSG:4326").iloc[0]

        props_rows = [fc_in["features"][m]["properties"] for m in members]
        acts = [p.get("activity_index") or 0 for p in props_rows]
        names = [p.get("farm") for p in props_rows if p.get("farm")]
        locs = [p.get("location") for p in props_rows if p.get("location")]
        name = (Counter(names).most_common(1)[0][0] if names
                else (f"Holding near {Counter(locs).most_common(1)[0][0]}" if locs
                      else f"Holding {fid + 1}"))
        mean_act = round(sum(acts) / len(acts), 3)
        footprint = round(float(sub.geometry.area.sum()))
        yard_ha = round(float(hull.area) / 10000.0, 1)
        land_ha = _nearby_farmland_ha(cent_wgs) if land else None

        feats.append({
            "type": "Feature",
            "properties": {
                "farm_id": fid, "name": name,
                "n_buildings": len(members),
                "activity_index": mean_act,
                "min_activity": round(min(acts), 3),
                "footprint_m2": footprint,
                "yard_ha": yard_ha,
                "land_ha": land_ha,
                "postcode": next((p.get("postcode") for p in props_rows if p.get("postcode")), ""),
            },
            "geometry": mapping(hull_wgs),
        })
        print(f"  holding {fid + 1}: {name} — {len(members)} bld, "
              f"act {mean_act}, land {land_ha if land_ha is not None else '?'} ha")

    json.dump({"type": "FeatureCollection", "features": feats}, open(out_path, "w"))
    json.dump(fc_in, open(in_path, "w"))  # write farm_id back into the buildings
    print(f"Wrote {out_path} ({len(feats)} holdings) and tagged buildings in {in_path}")
    return len(feats)
