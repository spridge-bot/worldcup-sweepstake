"""Build an Area of Interest box from a UK postcode.

Runs on a machine WITH internet (e.g. the Mac). Uses postcodes.io (free, no key)
with an OpenStreetMap Nominatim fallback, then writes a square AOI of the given
radius centred on the postcode — so the pipeline searches right around you.
"""
from __future__ import annotations

import json
import math

import requests

UA = {"User-Agent": "uk-land-monitoring/0.1 (storage finder)"}


def geocode_postcode(postcode: str) -> tuple[float, float]:
    """Return (lat, lon) for a UK postcode."""
    pc = postcode.replace(" ", "").upper()
    try:
        r = requests.get(f"https://api.postcodes.io/postcodes/{pc}", timeout=20)
        if r.ok:
            res = r.json().get("result") or {}
            if res.get("latitude") is not None:
                return float(res["latitude"]), float(res["longitude"])
    except Exception:
        pass
    # Fallback: Nominatim
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": f"{postcode}, UK", "format": "jsonv2", "limit": 1},
                         headers=UA, timeout=20)
        if r.ok and r.json():
            j = r.json()[0]
            return float(j["lat"]), float(j["lon"])
    except Exception:
        pass
    raise RuntimeError(f"Could not geocode postcode '{postcode}'. Check it and your connection.")


def aoi_ring(lat: float, lon: float, radius_km: float) -> list:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)))
    return [[[lon - dlon, lat - dlat], [lon + dlon, lat - dlat],
             [lon + dlon, lat + dlat], [lon - dlon, lat + dlat],
             [lon - dlon, lat - dlat]]]


def build(postcode: str, radius_km: float, out_path: str) -> tuple[float, float]:
    lat, lon = geocode_postcode(postcode)
    fc = {"type": "FeatureCollection", "name": f"aoi_{postcode.replace(' ', '')}",
          "features": [{"type": "Feature",
                        "properties": {"name": postcode, "radius_km": radius_km},
                        "geometry": {"type": "Polygon",
                                     "coordinates": aoi_ring(lat, lon, radius_km)}}]}
    with open(out_path, "w") as fh:
        json.dump(fc, fh, indent=2)
    print(f"Geocoded {postcode} -> {lat:.5f}, {lon:.5f}; "
          f"wrote {out_path} ({radius_km} km box, ~{radius_km*2:.0f} km across)")
    return lat, lon
