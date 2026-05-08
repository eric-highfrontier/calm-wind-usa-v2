#!/usr/bin/env python3
"""Download ERA5 hourly u100/v100 over CONUS + Alaska for the top-map coarse overlay.

Years 2020-2023, hourly, 0.25° native ERA5 resolution. 4 separate requests
(one per year) keeps each below the CDS per-job size cap and lets the queue
parallelise.

Outputs: data/era5/conus_coarse/era5_conus_<year>.nc
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "era5" / "conus_coarse"

# CONUS + Alaska. CDS expects [North, West, South, East].
AREA = [72, -170, 18, -65]
YEARS = [2023]  # single year is enough for the top-map coarse overlay
DAYS = [f"{d:02d}" for d in range(1, 32)]
HOURS = [f"{h:02d}:00" for h in range(24)]

# 100 m wind components — matches GWA standard / HALE balloon launch altitude.
# 0.5° grid keeps each per-month CDS request inside the cost cap.
VARS = ["100m_u_component_of_wind", "100m_v_component_of_wind"]
GRID = [0.5, 0.5]


def submit(year: int, month: int) -> Path:
    import cdsapi
    out = OUT / f"era5_conus_{year}_{month:02d}.nc"
    if out.exists() and out.stat().st_size > 5_000_000:
        return out
    OUT.mkdir(parents=True, exist_ok=True)
    c = cdsapi.Client(quiet=True)
    print(f"[fetch] CONUS+AK {year}-{month:02d}")
    c.retrieve(
        "reanalysis-era5-single-levels",
        {
            "product_type": "reanalysis",
            "format": "netcdf",
            "variable": VARS,
            "year": str(year),
            "month": f"{month:02d}",
            "day": DAYS,
            "time": HOURS,
            "area": AREA,
            "grid": GRID,
        },
        str(out),
    )
    print(f"  ✓ {out.name} {out.stat().st_size//(1024**2)} MB")
    return out


def main() -> None:
    import concurrent.futures as cf
    targets = []
    for y in YEARS if len(sys.argv) <= 1 else [int(a) for a in sys.argv[1:]]:
        for m in range(1, 13):
            targets.append((y, m))
    print(f"submitting {len(targets)} CDS jobs")
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(submit, y, m) for y, m in targets]
        for f in cf.as_completed(futs):
            try:
                f.result()
            except Exception as e:
                print(f"  ✗ {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
