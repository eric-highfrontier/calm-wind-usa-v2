#!/usr/bin/env python3
"""Compute calm-wind statistics from an ERA5 hourly NetCDF.

Outputs an N-D NetCDF containing % of days where wind < threshold for ≥H consecutive
hours, for thresholds [1.0, 1.5, 2.0, 2.5, 3.0] m/s × hours [1, 2, 3] × periods
[Annual, Jan..Dec]. 15 annual + 180 monthly = 195 combos.

Variables in output:
    pct_t{T}_h{H}_annual       (lat, lon)  float32
    pct_t{T}_h{H}_m{MM}        (lat, lon)  float32
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import xarray as xr
from numba import jit, prange

THRESHOLDS = [1.0, 1.5, 2.0, 2.5, 3.0]
HOURS = [1, 2, 3]


@jit(nopython=True, parallel=True, cache=True)
def calm_pct(wspd: np.ndarray, thresh: float, min_hours: int) -> np.ndarray:
    """% of full days containing ≥1 calm run of `min_hours` consecutive hours below `thresh`.
    `wspd`: (T, Y, X), T is a multiple of 24."""
    T, Y, X = wspd.shape
    n_days = T // 24
    out = np.zeros((Y, X), dtype=np.float32)
    for j in prange(Y):
        for i in range(X):
            ts = wspd[:, j, i]
            calm_days = 0
            for d in range(n_days):
                run = 0
                day_has = False
                for t in range(d * 24, (d + 1) * 24):
                    if ts[t] < thresh:
                        run += 1
                        if run >= min_hours:
                            day_has = True
                    else:
                        run = 0
                if day_has:
                    calm_days += 1
            out[j, i] = (calm_days / n_days) * 100.0 if n_days else 0.0
    return out


def detect_uv_names(ds: xr.Dataset) -> tuple[str, str]:
    """ARCO uses '100m_u_component_of_wind', CDS uses 'u100' — handle both."""
    u_candidates = ["100m_u_component_of_wind", "u100"]
    v_candidates = ["100m_v_component_of_wind", "v100"]
    u = next((n for n in u_candidates if n in ds.data_vars), None)
    v = next((n for n in v_candidates if n in ds.data_vars), None)
    if not u or not v:
        raise RuntimeError(f"u/v 100 m vars not found. data_vars: {list(ds.data_vars)}")
    return u, v


def detect_time_dim(ds: xr.Dataset) -> str:
    for cand in ("time", "valid_time"):
        if cand in ds.dims:
            return cand
    raise RuntimeError(f"no time dim, dims: {list(ds.dims)}")


def compute(input_nc: Path | list[Path], output_nc: Path, monthly: bool = True) -> None:
    if isinstance(input_nc, list):
        print(f"[load] {len(input_nc)} files via open_mfdataset")
        ds = xr.open_mfdataset(sorted(input_nc), combine="by_coords", parallel=False).load()
    else:
        print(f"[load] {input_nc}")
        ds = xr.open_dataset(input_nc)
    u_name, v_name = detect_uv_names(ds)
    t_dim = detect_time_dim(ds)
    # rename for convenience
    ds = ds.rename({u_name: "u", v_name: "v", t_dim: "time"})
    if "longitude" in ds.coords:
        ds = ds.rename({"longitude": "lon"})
    if "latitude" in ds.coords:
        ds = ds.rename({"latitude": "lat"})
    # ARCO is 0-360; convert to -180..180 if needed
    if float(ds.lon.max()) > 180:
        ds = ds.assign_coords(lon=(((ds.lon + 180) % 360) - 180)).sortby("lon")
    # ascending lat for raster output
    if float(ds.lat[0]) > float(ds.lat[-1]):
        ds = ds.sortby("lat")
    # Truncate to whole days
    n = (ds.sizes["time"] // 24) * 24
    ds = ds.isel(time=slice(0, n))
    wspd = np.sqrt(ds["u"].values ** 2 + ds["v"].values ** 2).astype(np.float32)
    print(f"[shape] wspd={wspd.shape} thresholds={THRESHOLDS} hours={HOURS}")

    months = ds["time"].dt.month.values

    out_vars = {}
    for T in THRESHOLDS:
        for H in HOURS:
            tag = f"t{T:.1f}_h{H}".replace(".", "_")
            print(f"[calm] {tag} annual")
            out_vars[f"pct_{tag}_annual"] = (("lat", "lon"), calm_pct(wspd, T, H))
            if monthly:
                for m in range(1, 13):
                    mask = months == m
                    sub = wspd[mask]
                    n_full = (sub.shape[0] // 24) * 24
                    sub = sub[:n_full]
                    if sub.shape[0] >= 24:
                        out_vars[f"pct_{tag}_m{m:02d}"] = (("lat", "lon"), calm_pct(sub, T, H))

    out = xr.Dataset(
        out_vars,
        coords={"lat": ds["lat"].values, "lon": ds["lon"].values},
        attrs={
            "source": str(input_nc),
            "thresholds_mps": THRESHOLDS,
            "hours": HOURS,
            "calm_pct_definition": "% of full days containing ≥1 calm run of H consecutive hours below threshold T",
        },
    )
    output_nc.parent.mkdir(parents=True, exist_ok=True)
    enc = {v: {"zlib": True, "complevel": 4} for v in out.data_vars}
    out.to_netcdf(output_nc, encoding=enc)
    print(f"[done] {output_nc} ({output_nc.stat().st_size // (1024**2)} MB, {len(out.data_vars)} vars)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, nargs="+", help="one .nc, or many monthly .nc to concat")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--annual-only", action="store_true")
    args = ap.parse_args()
    paths = args.input if len(args.input) > 1 else args.input[0]
    compute(paths, args.output, monthly=not args.annual_only)


if __name__ == "__main__":
    main()
