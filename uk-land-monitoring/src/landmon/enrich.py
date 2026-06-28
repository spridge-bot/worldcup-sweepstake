"""Enrich building features with a location name, farm name, and lookup links.

Run this on a machine WITH internet (e.g. the Mac). It uses free OpenStreetMap
services — Nominatim (reverse geocode) and Overpass (nearest named farm), no API
key — and adds, per building:
  location : nearest place (road / hamlet / village + postcode)
  farm     : best-guess farm/holding name if OSM has one nearby
  postcode : nearest postcode if found
  links    : [{label,url}] legitimate ways to find ownership/contact

We deliberately DO NOT fetch owners' names, phone numbers or other personal
contact details — that would be a privacy/GDPR concern and is unreliable. Instead
we link to the official/legitimate lookups (HM Land Registry, council planning).
"""
from __future__ import annotations

import json
import time
import urllib.parse

import requests

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
OVERPASS = "https://overpass-api.de/api/interpreter"
UA = {"User-Agent": "uk-land-monitoring/0.1 (rural storage finder)"}


def _centroid(geom: dict) -> tuple[float, float]:
    """Rough centroid (lon, lat) of a Polygon/MultiPolygon exterior ring."""
    coords = geom["coordinates"]
    ring = coords[0] if geom["type"] == "Polygon" else coords[0][0]
    pts = ring[:-1] if len(ring) > 1 else ring
    xs = [c[0] for c in pts]
    ys = [c[1] for c in pts]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _reverse(lat: float, lon: float) -> dict:
    try:
        r = requests.get(NOMINATIM, params={
            "lat": lat, "lon": lon, "format": "jsonv2",
            "zoom": 16, "addressdetails": 1, "namedetails": 1},
            headers=UA, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def _overpass_farm(lat: float, lon: float, radius: int = 350) -> str | None:
    q = (f'[out:json][timeout:20];('
         f'way(around:{radius},{lat},{lon})["name"~"[Ff]arm"];'
         f'node(around:{radius},{lat},{lon})["name"~"[Ff]arm"];'
         f');out tags 1;')
    try:
        r = requests.post(OVERPASS, data=q, headers=UA, timeout=30)
        r.raise_for_status()
        els = r.json().get("elements", [])
        if els:
            return els[0].get("tags", {}).get("name")
    except Exception:
        pass
    return None


def _links(lat: float, lon: float, place: str | None, postcode: str | None) -> list[dict]:
    query = " ".join(p for p in [place, postcode, "farm Oxfordshire"] if p)
    g = urllib.parse.quote(query)
    pc = urllib.parse.quote(postcode) if postcode else ""
    out = [
        {"label": "🔎 Web search", "url": f"https://www.google.com/search?q={g}"},
        {"label": "🗺️ Google Maps", "url": f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"},
        {"label": "🏛️ Who owns it (Land Registry)",
         "url": (f"https://search-property-information.service.gov.uk/search/search-by-postcode?postcode={pc}"
                 if pc else "https://www.gov.uk/search-property-information-land-registry")},
        {"label": "💷 Sold prices / when last sold",
         "url": (f"https://www.rightmove.co.uk/house-prices/{postcode.replace(' ', '-')}.html"
                 if postcode else "https://landregistry.data.gov.uk/app/ppd")},
        {"label": "📋 Planning history (Cherwell DC)", "url": "https://planningregister.cherwell.gov.uk/"},
    ]
    return out


def enrich(in_path: str, out_path: str, sleep: float = 1.0) -> None:
    """Add location/farm/links to every feature. sleep keeps us within
    Nominatim's ~1 request/second usage policy."""
    fc = json.load(open(in_path))
    feats = fc.get("features", [])
    print(f"Enriching {len(feats)} buildings (≈{int(len(feats) * sleep)}s)…")
    for i, f in enumerate(feats):
        p = f.setdefault("properties", {})
        lon, lat = _centroid(f["geometry"])
        rev = _reverse(lat, lon)
        addr = rev.get("address", {}) or {}
        postcode = addr.get("postcode")
        place = (addr.get("road") or addr.get("hamlet") or addr.get("village")
                 or addr.get("suburb") or addr.get("town") or addr.get("county"))
        # Farm name: prefer the matched OSM feature name if it mentions "farm",
        # else an address 'farm' part, else the nearest named farm via Overpass.
        farm = (rev.get("namedetails", {}) or {}).get("name")
        if farm and "farm" not in farm.lower():
            farm = None
        farm = farm or addr.get("farm") or _overpass_farm(lat, lon)
        loc_bits = [b for b in [addr.get("road"),
                                addr.get("hamlet") or addr.get("village") or addr.get("town"),
                                postcode] if b]
        p["location"] = ", ".join(dict.fromkeys(loc_bits)) or "Unknown location"
        p["farm"] = farm or ""
        p["postcode"] = postcode or ""
        p["links"] = _links(round(lat, 5), round(lon, 5), place, postcode)
        print(f"  [{i + 1}/{len(feats)}] {p['farm'] or p['location']}")
        time.sleep(sleep)
    json.dump(fc, open(out_path, "w"))
    print(f"Wrote {out_path}")
