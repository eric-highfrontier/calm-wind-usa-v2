#!/usr/bin/env python3
"""Per-spaceport ERA5 download using monthly CDS chunks.

CDS rejects per-year-per-bbox requests with "cost limits exceeded" but accepts
monthly ones (each ~3000 fields). We submit `slug × year × month` (= 240 jobs
per slug × 4 yr × 12 mo) into a thread pool capped at 12 concurrent (CDS allows
~20 user-wide). After all months for a (slug, year) land we concat into a
single per-year NetCDF and delete the monthly chunks.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import sys
from pathlib import Path

import xarray as xr

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "data" / "sites.json"
OUT = ROOT / "data" / "era5" / "per_site"

YEARS = [2020, 2021, 2022, 2023]
DAYS = [f"{d:02d}" for d in range(1, 32)]
HOURS = [f"{h:02d}:00" for h in range(24)]
VARS = [
    "100m_u_component_of_wind",
    "100m_v_component_of_wind",
    "2m_temperature",
]
HALF = 0.75


def site_area(lat: float, lon: float) -> list[float]:
    return [round(lat + HALF, 3), round(lon - HALF, 3),
            round(lat - HALF, 3), round(lon + HALF, 3)]


def fetch_month(slug: str, lat: float, lon: float, year: int, month: int) -> Path | None:
    import cdsapi
    out_dir = OUT / slug / "_monthly"
    out = out_dir / f"{slug}_{year}_{month:02d}.nc"
    if out.exists() and out.stat().st_size > 100_000:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    c = cdsapi.Client(quiet=True)
    print(f"[fetch] {slug} {year}-{month:02d}")
    try:
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
                "area": site_area(lat, lon),
                "grid": [0.25, 0.25],
            },
            str(out),
        )
        return out
    except Exception as e:
        print(f"  ✗ {slug} {year}-{month:02d}: {e}", file=sys.stderr)
        return None


def consolidate_year(slug: str, year: int) -> Path | None:
    monthly_dir = OUT / slug / "_monthly"
    out = OUT / slug / f"{slug}_{year}.nc"
    if out.exists() and out.stat().st_size > 1_000_000:
        return out
    files = sorted(monthly_dir.glob(f"{slug}_{year}_*.nc"))
    if len(files) < 12:
        print(f"[wait] {slug} {year}: have {len(files)}/12 months — skipping consolidate")
        return None
    print(f"[concat] {slug} {year}: {len(files)} files")
    ds = xr.open_mfdataset(files, combine="by_coords").load()
    enc = {v: {"zlib": True, "complevel": 4} for v in ds.data_vars}
    ds.to_netcdf(out, encoding=enc)
    ds.close()
    print(f"  ✓ {out.name} {out.stat().st_size//(1024**2)} MB")
    # tidy up — remove monthly chunks
    for f in files:
        f.unlink()
    return out


def main() -> None:
    sites = json.loads(SITES.read_text())["sites"]
    if len(sys.argv) > 1:
        sel = set(sys.argv[1:])
        sites = [s for s in sites if s["slug"] in sel]
    jobs = [(s["slug"], s["lat"], s["lon"], y, m)
            for s in sites for y in YEARS for m in range(1, 13)]
    print(f"submitting {len(jobs)} CDS jobs ({len(sites)} sites × {len(YEARS)} yr × 12 mo)")
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        list(cf.as_completed([ex.submit(fetch_month, *j) for j in jobs]))
    print("[concat] consolidating per-year files...")
    for s in sites:
        for y in YEARS:
            try:
                consolidate_year(s["slug"], y)
            except Exception as e:
                print(f"  ✗ consolidate {s['slug']} {y}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
