"""landmon — UK land/building monitoring toolkit.

Pipeline:
  1. aoi      — load/define an Area of Interest (Oxfordshire farmland).
  2. os_data  — OS Maps basemap tiles + OS NGD building/land vectors.
  3. buildings— flag farm-storage / industrial-storage buildings on farms.
  4. sentinel — free Sentinel-2 / Sentinel-1 time series (Planetary Computer).
  5. change   — turn the time series into per-building "activity" metrics.

See ../../docs/research-report.md for the data-source and feasibility research.
"""

__version__ = "0.1.0"

__all__ = ["aoi", "os_data", "buildings", "sentinel", "change"]
