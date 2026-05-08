#!/usr/bin/env python3
"""Render a calm-stat NetCDF to a Slippy-Map (Z/X/Y) PNG tile pyramid.

Uses the GWA-standard 11-stop colormap from the calm-winds-spain pipeline
(white→cyan→blue→green→yellow→orange→red→purple). One PNG tile per Z/X/Y at
256×256 with cubic interpolation, alpha=255, calm 0% → purple, 100% → white.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image
from scipy.interpolate import RegularGridInterpolator

# 11-stop GWA colormap. First col = calm pct, then RGB.
CMAP = np.array([
    [0,   180,   0, 180],   # purple — windiest
    [15,  255,   0,   0],   # red
    [30,  255, 165,   0],   # orange
    [50,  255, 255,   0],   # yellow
    [60,    0, 200,   0],   # green
    [70,    0,   0, 180],   # blue
    [90,    0, 255, 255],   # cyan
    [100, 255, 255, 255],   # white — calmest
], dtype=np.float32)


def colorize(pct: np.ndarray) -> np.ndarray:
    """Map calm-% array → RGBA uint8 array of same H,W."""
    pct_clip = np.clip(pct, 0, 100)
    out = np.zeros(pct_clip.shape + (4,), dtype=np.uint8)
    for k in range(len(CMAP) - 1):
        lo, hi = CMAP[k], CMAP[k + 1]
        m = (pct_clip >= lo[0]) & (pct_clip <= hi[0])
        if not m.any():
            continue
        f = (pct_clip[m] - lo[0]) / (hi[0] - lo[0])
        out[m, 0] = (lo[1] + f * (hi[1] - lo[1])).astype(np.uint8)
        out[m, 1] = (lo[2] + f * (hi[2] - lo[2])).astype(np.uint8)
        out[m, 2] = (lo[3] + f * (hi[3] - lo[3])).astype(np.uint8)
        out[m, 3] = 255
    out[np.isnan(pct), 3] = 0
    return out


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) lon/lat of a slippy tile."""
    n = 2.0 ** z
    lon_w = x / n * 360 - 180
    lon_e = (x + 1) / n * 360 - 180
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_w, lat_s, lon_e, lat_n


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2.0 ** z
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * n)
    return x, y


def render(calm_nc: Path, var: str, out_root: Path, z_min: int, z_max: int,
           tile_size: int = 256) -> None:
    ds = xr.open_dataset(calm_nc)
    if var not in ds.data_vars:
        raise SystemExit(f"variable {var} not in {calm_nc} (have: {sorted(ds.data_vars)[:5]}...)")
    arr = ds[var].values  # (lat, lon)
    lat = ds["lat"].values
    lon = ds["lon"].values
    lat_asc = lat if lat[0] < lat[-1] else lat[::-1]
    arr_asc = arr if lat[0] < lat[-1] else arr[::-1, :]
    interp = RegularGridInterpolator(
        (lat_asc, lon), arr_asc, bounds_error=False, fill_value=np.nan, method="linear"
    )

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
                # Skip tiles entirely outside data
                if e < west_d or w > east_d or n_ < south_d or s > north_d:
                    continue
                # Sample tile_size×tile_size pixel grid
                xs = np.linspace(w, e, tile_size, dtype=np.float64)
                ys = np.linspace(n_, s, tile_size, dtype=np.float64)  # north→south
                ll, la = np.meshgrid(xs, ys)
                samples = interp(np.stack([la.ravel(), ll.ravel()], axis=-1))
                samples = samples.reshape(tile_size, tile_size).astype(np.float32)
                # Mask anything outside the data box (beyond fill_value=NaN)
                rgba = colorize(samples)
                if rgba[..., 3].sum() == 0:
                    continue
                out_path = out_root / str(z) / str(x) / f"{y}.png"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(rgba, "RGBA").save(out_path, "PNG", optimize=True)
                n_written += 1
        print(f"[z{z}] cumulative tiles: {n_written}")
    print(f"[done] wrote {n_written} tiles → {out_root}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("calm_nc", type=Path, help="input calm stats .nc")
    ap.add_argument("out_root", type=Path, help="output tile dir")
    ap.add_argument("--var", default="pct_t2_0_h2_annual")
    ap.add_argument("--z-min", type=int, default=3)
    ap.add_argument("--z-max", type=int, default=6)
    args = ap.parse_args()
    render(args.calm_nc, args.var, args.out_root, args.z_min, args.z_max)


if __name__ == "__main__":
    main()
