#!/usr/bin/env python3
"""Fetch ERA5 from the Google Public Datasets ARCO zarr — free, no auth, no
CDS cost cap. Pulls 100 m u/v hourly for an arbitrary bbox + year.

The ARCO ERA5 cube lives at:
    gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3
Hosted publicly (Google + ECMWF), 1979-present, hourly, 0.25° native grid.
Reference: https://cloud.google.com/storage/docs/public-datasets/era5

This script is the drop-in replacement for the CDS calls. We open the zarr
lazily via xarray, slice the box/time, and serialize to a NetCDF on disk.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import xarray as xr

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "data" / "sites.json"
ARCO_URL = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
VARS = ["100m_u_component_of_wind", "100m_v_component_of_wind"]
HALF = 0.75  # site bbox half-width (degrees)


def open_arco() -> xr.Dataset:
    return xr.open_zarr(
        ARCO_URL,
        chunks={"time": 24},  # one day per chunk for sane memory
        storage_options={"token": "anon"},
        consolidated=True,
    )


def normalize_lon(lon: float) -> float:
    """ARCO ERA5 uses 0-360 longitude."""
    return lon if lon >= 0 else lon + 360


def fetch_box(ds: xr.Dataset, north: float, west: float, south: float, east: float,
              t_start: str, t_end: str, out: Path,
              extra_vars: list[str] | None = None) -> Path:
    if out.exists() and out.stat().st_size > 1_000_000:
        print(f"[skip] {out.name} ({out.stat().st_size//(1024**2)} MB)")
        return out
    out.parent.mkdir(parents=True, exist_ok=True)

    var_list = list(VARS)
    if extra_vars:
        for v in extra_vars:
            if v not in var_list and v in ds.data_vars:
                var_list.append(v)

    w360 = normalize_lon(west)
    e360 = normalize_lon(east)
    # ARCO latitude is descending (90 → -90); slice from north to south.
    sub = ds[var_list].sel(
        time=slice(t_start, t_end),
        latitude=slice(north, south),
        longitude=slice(w360, e360) if w360 < e360 else None,
    )
    if w360 >= e360:
        # cross-meridian wrap not needed for our sites (all in W hemisphere)
        raise ValueError("west must be < east in 0-360 frame")
    print(f"[fetch] {out.name}  shape={ {d: sub.sizes[d] for d in sub.dims} }  vars={var_list}")
    sub = sub.load()
    enc = {v: {"zlib": True, "complevel": 4} for v in sub.data_vars}
    sub.to_netcdf(out, engine="netcdf4", encoding=enc)
    print(f"  ✓ {out.stat().st_size // (1024**2)} MB")
    return out


def fetch_conus(year: int) -> Path:
    """Single-year CONUS+AK, hourly u100/v100 — used for top-map coarse layer."""
    out = ROOT / "data" / "era5" / "conus_coarse" / f"era5_conus_{year}.nc"
    ds = open_arco()
    return fetch_box(ds, 72, -170, 18, -65,
                     f"{year}-01-01", f"{year}-12-31T23:00", out)


def fetch_per_site(slug: str, lat: float, lon: float, years: list[int]) -> list[Path]:
    ds = open_arco()
    paths = []
    for y in years:
        out = ROOT / "data" / "era5" / "per_site" / slug / f"{slug}_{y}.nc"
        north, west, south, east = lat + HALF, lon - HALF, lat - HALF, lon + HALF
        # Add 2 m temperature for diurnal-phase signal
        p = fetch_box(ds, north, west, south, east,
                      f"{y}-01-01", f"{y}-12-31T23:00", out,
                      extra_vars=["2m_temperature"])
        paths.append(p)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["conus", "site"])
    ap.add_argument("--years", type=int, nargs="+", default=[2023])
    ap.add_argument("--slug", help="site slug (only for mode=site; default: all sites)")
    args = ap.parse_args()

    if args.mode == "conus":
        for y in args.years:
            fetch_conus(y)
    else:
        sites = json.loads(SITES.read_text())["sites"]
        if args.slug:
            sites = [s for s in sites if s["slug"] == args.slug]
            if not sites:
                print(f"slug {args.slug} not in sites.json", file=sys.stderr)
                sys.exit(1)
        for s in sites:
            fetch_per_site(s["slug"], s["lat"], s["lon"], args.years)


if __name__ == "__main__":
    main()
