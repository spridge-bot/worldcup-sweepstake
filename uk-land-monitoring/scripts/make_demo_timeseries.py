#!/usr/bin/env python3
"""Generate demo data so the viewer + time-slider work with no key/network.

Writes:
  sample_data/demo_storage.geojson        7 buildings + per-date `timeline`
  sample_data/demo_chips/<id>/<date>.svg   a dated "imagery" chip per building

Deterministic (no randomness) so the committed output is stable. The chips are
stylised stand-ins for real satellite chips: a field backdrop, the building, and
little "vehicle" marks whose count tracks that date's activity — so the animation
visibly shows busy vs idle over time. Replace with real data via the pipeline.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW, HH = 0.00045, 0.00030  # half-width/height of each footprint in degrees

# id, name, class, storage_score, area, (lon, lat), base, trend, amp, phase_month
BUILDINGS = [
    ("demo-1", "Bickerton Barns",      "farm_storage",       0.72, 612, (-1.2800, 51.8400), 0.15, 0.05, 0.08, 6),
    ("demo-2", "Otmoor Grain Store",   "farm_storage",       0.81, 980, (-1.2720, 51.8480), 0.25, 0.00, 0.25, 7),
    ("demo-3", "Manor Farm Workshop",  "industrial_storage", 0.69, 430, (-1.2650, 51.8520), 0.45, 0.20, 0.10, 2),
    ("demo-4", "Lower Field Sheds",    "farm_storage",       0.64, 355, (-1.2580, 51.8440), 0.20, 0.05, 0.12, 8),
    ("demo-5", "Greenway Units",       "industrial_storage", 0.76, 720, (-1.2520, 51.8570), 0.35, 0.50, 0.07, 0),
    ("demo-6", "Hill Copse Garage",    "possible_storage",   0.55, 210, (-1.2760, 51.8570), 0.35, 0.10, 0.18, 4),
    ("demo-7", "Brookside Dutch Barn", "farm_storage",       0.67, 540, (-1.2620, 51.8380), 0.05, 0.00, 0.03, 0),
]

# Quarterly captures across two years (8 dates) — enough to see change animate.
DATES = [(y, m) for y in (2023, 2024) for m in (1, 4, 7, 10)]


def activity(base, trend, amp, phase, i, month):
    t = i / (len(DATES) - 1)
    seasonal = amp * math.sin(2 * math.pi * (month - phase) / 12.0)
    return max(0.0, min(1.0, base + trend * t + seasonal))


def footprint(lon, lat):
    return [[[lon - HW, lat - HH], [lon + HW, lat - HH],
             [lon + HW, lat + HH], [lon - HW, lat + HH], [lon - HW, lat - HH]]]


def lcg(seed):
    """Tiny deterministic PRNG for stable 'vehicle' placement."""
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF


def chip_svg(name, date, a, month):
    """Stylised dated imagery chip; busier dates show more vehicle marks."""
    # Field greener in summer, browner in winter.
    green = int(150 + 70 * math.sin(2 * math.pi * (month - 4) / 12.0))
    field = f"rgb({90 + (255-green)//4},{max(80, min(190, green))},70)"
    rng = lcg(sum(map(ord, name + date)))
    n_veh = round(a * 9)
    vehicles = ""
    for _ in range(n_veh):
        vx = 8 + next(rng) * 48
        vy = 30 + next(rng) * 26
        vehicles += f'<rect x="{vx:.1f}" y="{vy:.1f}" width="4" height="3" fill="#2b2b2b"/>'
    bar = int(a * 60)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" fill="{field}"/>'
        f'<rect x="6" y="10" width="34" height="16" fill="#9a9a9a" stroke="#555"/>'  # building
        f'<rect x="6" y="28" width="52" height="30" fill="#b8a98a" opacity="0.55"/>'  # yard
        f'{vehicles}'
        f'<rect x="2" y="2" width="{bar}" height="3" fill="#d7191c"/>'  # activity bar
        f'<text x="3" y="62" font-family="monospace" font-size="7" fill="#fff">{date}</text>'
        f'</svg>'
    )


def main():
    features, chip_root = [], ROOT / "sample_data" / "demo_chips"
    for bid, name, cls, score, area, (lon, lat), base, trend, amp, phase in BUILDINGS:
        timeline, vals = [], []
        for i, (y, m) in enumerate(DATES):
            date = f"{y}-{m:02d}-15"
            a = round(activity(base, trend, amp, phase, i, m), 3)
            timeline.append({"d": date, "a": a})
            vals.append(a)
            d = chip_root / bid
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{date}.svg").write_text(chip_svg(name, date, a, m))
        features.append({
            "type": "Feature",
            "properties": {
                "id": bid, "name": name, "storage_class": cls,
                "storage_score": score, "area_m2": area,
                "activity_index": round(sum(vals) / len(vals), 3),
                "timeline": timeline,
            },
            "geometry": {"type": "Polygon", "coordinates": footprint(lon, lat)},
        })

    fc = {"type": "FeatureCollection", "name": "demo_storage_oxfordshire",
          "comment": "Synthetic demo with per-date timelines + chips. Regenerate "
                     "with scripts/make_demo_timeseries.py.",
          "features": features}
    out = ROOT / "sample_data" / "demo_storage.geojson"
    out.write_text(json.dumps(fc, indent=2))
    print(f"Wrote {out} ({len(features)} buildings) and "
          f"{len(DATES) * len(BUILDINGS)} chips under {chip_root}")


if __name__ == "__main__":
    main()
