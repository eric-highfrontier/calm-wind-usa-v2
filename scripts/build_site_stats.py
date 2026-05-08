#!/usr/bin/env python3
"""Compute representative calm % per site at the default settings (annual,
t=2.0 m/s, h=2 hr) — a single number that summarises how operationally calm
the spaceport itself is. Pixel chosen at the site's exact lat/lon.

Output: deploy_real_us/data/site_stats.json — { slug: {default_calm_pct, max_calm_pct, mean_wind_mps} }
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import xarray as xr
import rasterio

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "data" / "sites.json"
CALM_DIR = ROOT / "data" / "calm"
GWA_WS = ROOT / "data/gwa/gwa_usa_wind_speed_100m.tif"
OUT = ROOT / "deploy_real_us" / "data" / "site_stats.json"


def site_value(arr: np.ndarray, lats: np.ndarray, lons: np.ndarray,
               lat: float, lon: float) -> float:
    i = int(np.argmin(np.abs(lats - lat)))
    j = int(np.argmin(np.abs(lons - lon)))
    return float(arr[i, j])


def gwa_value(lat: float, lon: float) -> float:
    if not GWA_WS.exists():
        return float("nan")
    with rasterio.open(GWA_WS) as src:
        col, row = ~src.transform * (lon, lat)
        col, row = int(col), int(row)
        if 0 <= row < src.height and 0 <= col < src.width:
            v = float(src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
            if v <= 0 or v > 50:
                return float("nan")
            return v
    return float("nan")


def main() -> None:
    sites = json.loads(SITES.read_text())["sites"]
    out = {}
    for s in sites:
        slug = s["slug"]
        lat, lon = s["lat"], s["lon"]
        nc_path = CALM_DIR / f"{slug}.nc"
        d = {}
        if nc_path.exists():
            ds = xr.open_dataset(nc_path)
            v_default = ds["pct_t2_0_h2_annual"].values
            lats = ds["lat"].values
            lons = ds["lon"].values
            d["default_calm_pct"] = round(site_value(v_default, lats, lons, lat, lon), 1)
            d["max_calm_pct"] = round(float(np.nanmax(v_default)), 1)
            d["mean_calm_pct"] = round(float(np.nanmean(v_default)), 1)
            ds.close()
        d["mean_wind_mps_gwa"] = round(gwa_value(lat, lon), 2)
        if d:
            out[slug] = d
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"wrote {OUT}")
    for s, v in out.items():
        print(f"  {s}: {v}")


if __name__ == "__main__":
    main()
