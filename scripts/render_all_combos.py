#!/usr/bin/env python3
"""Render all 195 calm-stat combos (annual + 12 months × 5 thresholds × 3 hours)
to tile pyramids under deploy_real_us/tiles/<slug>/. Loads calm.nc once."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image
from scipy.interpolate import RegularGridInterpolator

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_tiles import colorize, tile_bounds, lonlat_to_tile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
THRESHOLDS = ["1_0", "1_5", "2_0", "2_5", "3_0", "3_5", "4_0", "4_5", "5_0"]
HOURS = [1, 2, 3]
PERIODS = ["annual"] + [f"m{m:02d}" for m in range(1, 13)]


def render_one(arr: np.ndarray, lat: np.ndarray, lon: np.ndarray,
               out_root: Path, z_min: int, z_max: int) -> int:
    lat_asc = lat if lat[0] < lat[-1] else lat[::-1]
    arr_asc = arr if lat[0] < lat[-1] else arr[::-1, :]
    interp = RegularGridInterpolator((lat_asc, lon), arr_asc,
                                     bounds_error=False, fill_value=np.nan, method="linear")
    south_d, north_d = float(lat.min()), float(lat.max())
    west_d, east_d = float(lon.min()), float(lon.max())
    n_written = 0
    for z in range(z_min, z_max + 1):
        x0, y_n = lonlat_to_tile(west_d, north_d, z)
        x1, y_s = lonlat_to_tile(east_d, south_d, z)
        x_lo, x_hi = min(x0, x1), max(x0, x1)
        y_lo, y_hi = min(y_n, y_s), max(y_n, y_s)
        for x in range(x_lo, x_hi + 1):
            for y in range(y_lo, y_hi + 1):
                w, s, e, n_ = tile_bounds(z, x, y)
                if e < west_d or w > east_d or n_ < south_d or s > north_d:
                    continue
                xs = np.linspace(w, e, 256, dtype=np.float64)
                ys = np.linspace(n_, s, 256, dtype=np.float64)
                ll, la = np.meshgrid(xs, ys)
                samples = interp(np.stack([la.ravel(), ll.ravel()], axis=-1))
                samples = samples.reshape(256, 256).astype(np.float32)
                rgba = colorize(samples)
                if rgba[..., 3].sum() == 0:
                    continue
                out_path = out_root / str(z) / str(x) / f"{y}.png"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(rgba, "RGBA").save(out_path, "PNG", optimize=True)
                n_written += 1
    return n_written


def render(slug: str, calm_nc: Path, out_root: Path, z_min: int, z_max: int) -> None:
    print(f"[load] {calm_nc}")
    ds = xr.open_dataset(calm_nc)
    lat = ds["lat"].values
    lon = ds["lon"].values
    n_combos = len(PERIODS) * len(THRESHOLDS) * len(HOURS)
    n = 0
    total_tiles = 0
    for period in PERIODS:
        for T in THRESHOLDS:
            for H in HOURS:
                n += 1
                var = f"pct_t{T}_h{H}_{period}"
                out = out_root / period / f"t{T}_h{H}"
                if out.exists() and any(out.rglob("*.png")):
                    print(f"[{n}/{n_combos}] {var}: skip")
                    continue
                if var not in ds.data_vars:
                    print(f"[{n}/{n_combos}] {var}: NOT IN NC, skip")
                    continue
                arr = ds[var].values
                k = render_one(arr, lat, lon, out, z_min, z_max)
                total_tiles += k
                print(f"[{n}/{n_combos}] {var}: {k} tiles")
    print(f"[done] {total_tiles} tiles total")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--calm-nc", type=Path)
    ap.add_argument("--out-root", type=Path)
    ap.add_argument("--z-min", type=int, default=6)
    ap.add_argument("--z-max", type=int, default=12)
    args = ap.parse_args()
    calm = args.calm_nc or (ROOT / f"data/calm/{args.slug}.nc")
    out = args.out_root or (ROOT / f"deploy_real_us/tiles/{args.slug}")
    render(args.slug, calm, out, args.z_min, args.z_max)


if __name__ == "__main__":
    main()
