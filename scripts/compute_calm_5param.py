#!/usr/bin/env python3
"""5-parameter Weibull+Markov calm probability per spaceport.

Inputs
------
* GWA 250 m rasters      data/gwa/gwa_usa_wind_speed_100m.tif
                         data/gwa/gwa_usa_combined_Weibull_k_100m.tif
* ERA5 hourly time series for the site bbox
                         data/era5/per_site/<slug>/<slug>_<year>.nc
                         (or, in fallback, sliced from data/era5/conus_coarse/*)

The spatial pattern (mean wind, k) comes from GWA at 250 m. The temporal
parameters (diurnal_amp, diurnal_phase, autocorr) come from the ERA5 box mean
— same value applied across the whole 250 m grid, since these are local
synoptic-scale signals that don't vary much within ±0.75°.

Output
------
data/calm/<slug>.nc with 195 vars:
    pct_t{T}_h{H}_annual         (lat, lon)
    pct_t{T}_h{H}_m{MM}          (lat, lon)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds
import xarray as xr
from scipy import stats
from scipy.optimize import curve_fit
from scipy.special import gamma as gamma_fn

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "data" / "sites.json"
GWA_WS = ROOT / "data/gwa/gwa_usa_wind_speed_100m.tif"
GWA_K = ROOT / "data/gwa/gwa_usa_combined_Weibull_k_100m.tif"

THRESHOLDS = [1.0, 1.5, 2.0, 2.5, 3.0]
HOURS = [1, 2, 3]
HALF = 0.75  # site half-width in degrees


def load_site(slug: str) -> dict:
    sites = json.loads(SITES.read_text())["sites"]
    s = next((s for s in sites if s["slug"] == slug), None)
    if not s:
        raise SystemExit(f"site {slug} not in sites.json")
    return s


def clip_gwa(tif: Path, lat: float, lon: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with rasterio.open(tif) as src:
        west, south, east, north = lon - HALF, lat - HALF, lon + HALF, lat + HALF
        win = from_bounds(west, south, east, north, transform=src.transform)
        arr = src.read(1, window=win).astype(np.float32)
        # axes from window
        win_t = src.window_transform(win)
        rows, cols = arr.shape
        # row 0 = top (north). pixel-centre lat/lon
        ys = win_t.f + win_t.e * (np.arange(rows) + 0.5)
        xs = win_t.c + win_t.a * (np.arange(cols) + 0.5)
        # mask invalid
        nodata = src.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        arr[(arr <= 0) | (arr > 50)] = np.nan
    return arr, ys, xs


def load_era5(nc_paths: list[Path], lat: float | None = None, lon: float | None = None
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (wind_speed_hourly[T], hour_of_day[T], month[T]).

    If `lat`/`lon` provided AND files have a spatial extent larger than the site
    bbox, subset to ±HALF° before averaging.
    """
    if not nc_paths:
        raise SystemExit("no ERA5 files for site")
    ds = xr.open_mfdataset(sorted(nc_paths), combine="by_coords").load()
    if "latitude" in ds.coords and lat is not None:
        # Slice. ERA5 latitudes are usually in descending order in CDS files.
        lat_lo, lat_hi = lat - HALF, lat + HALF
        if float(ds.latitude[0]) > float(ds.latitude[-1]):
            ds = ds.sel(latitude=slice(lat_hi, lat_lo))
        else:
            ds = ds.sel(latitude=slice(lat_lo, lat_hi))
        if lon is not None:
            ds = ds.sel(longitude=slice(lon - HALF, lon + HALF))
    u_name = "u100" if "u100" in ds.data_vars else "100m_u_component_of_wind"
    v_name = "v100" if "v100" in ds.data_vars else "100m_v_component_of_wind"
    t_dim = "time" if "time" in ds.dims else "valid_time"
    u = ds[u_name].values
    v = ds[v_name].values
    times = ds[t_dim].values
    if u.ndim == 3:
        u_mean = np.nanmean(u, axis=(1, 2))
        v_mean = np.nanmean(v, axis=(1, 2))
    else:
        u_mean, v_mean = u, v
    wspd = np.sqrt(u_mean ** 2 + v_mean ** 2)
    hours_of_day = np.array([np.datetime64(t, "h").astype(np.int64) % 24 for t in times])
    months = np.array([np.datetime64(t, "M").astype(object).month for t in times])
    return wspd.astype(np.float32), hours_of_day.astype(np.int8), months.astype(np.int8)


def fit_diurnal(wind: np.ndarray, hours: np.ndarray) -> tuple[float, float]:
    means = np.array([np.nanmean(wind[hours == h]) for h in range(24)])
    if np.any(np.isnan(means)):
        return 0.0, 10.0
    def f(h, A, ph, off):
        return A * np.cos(2 * np.pi * (h - ph) / 24) + off
    try:
        A0 = (means.max() - means.min()) / 2
        ph0 = float(np.argmin(means))
        off0 = means.mean()
        popt, _ = curve_fit(f, np.arange(24), means, p0=[A0, ph0, off0],
                            bounds=([-10, 0, 0], [10, 24, 30]))
        amp, ph, _ = popt
        if amp < 0:
            amp = -amp
            ph = (ph + 12) % 24
        return float(abs(amp)), float(ph)
    except Exception:
        return float((means.max() - means.min()) / 2), float(np.argmin(means))


def lag1_autocorr(wind: np.ndarray) -> float:
    valid = wind[np.isfinite(wind)]
    if len(valid) < 100:
        return 0.95
    c = np.corrcoef(valid[:-1], valid[1:])[0, 1]
    return float(c) if np.isfinite(c) else 0.95


def calm_prob(mean: np.ndarray, k: np.ndarray, amp: float, phase: float, autocorr: float,
              threshold: float, hours: int) -> np.ndarray:
    mean_safe = np.maximum(mean, 0.1)
    k_safe = np.clip(k, 1.1, 4.0)
    p_sum = np.zeros_like(mean_safe)
    for h in range(24):
        wind_h = mean_safe + amp * np.cos(2 * np.pi * (h - phase) / 24)
        wind_h = np.maximum(wind_h, 0.1)
        c = wind_h / gamma_fn(1 + 1 / k_safe)
        p_sum += 1 - np.exp(-(threshold / c) ** k_safe)
    p_calm = p_sum / 24
    if hours > 1:
        pf = np.clip(1 + (autocorr - 0.5) * 0.6, 0.5, 1.5)
        p_calm = p_calm ** (hours / pf)
    return np.clip(p_calm * 100, 0, 100)


def compute_site(slug: str) -> Path:
    s = load_site(slug)
    lat, lon = s["lat"], s["lon"]
    print(f"[{slug}] lat={lat} lon={lon}")

    # Spatial: GWA
    print("  loading GWA mean...")
    mean, ys, xs = clip_gwa(GWA_WS, lat, lon)
    print(f"    mean shape {mean.shape}  finite {np.isfinite(mean).sum()}")
    print("  loading GWA k...")
    k_arr, _, _ = clip_gwa(GWA_K, lat, lon)
    if k_arr.shape != mean.shape:
        k_arr = np.full_like(mean, 2.0)

    # Temporal: ERA5 box-mean time series
    persite_dir = ROOT / "data/era5/per_site" / slug
    persite_files = list(persite_dir.glob(f"{slug}_*.nc"))
    persite_files = [p for p in persite_files if "_monthly" not in str(p)]
    if persite_files:
        print(f"  loading ERA5 per-site: {len(persite_files)} files")
    else:
        # fallback: use CONUS coarse, sliced
        print("  per-site ERA5 missing → using CONUS coarse (single year)")
        persite_files = sorted((ROOT / "data/era5/conus_coarse").glob("era5_conus_*.nc"))
    wspd, hours_of_day, months = load_era5(persite_files, lat=lat, lon=lon)

    # Compute monthly + annual temporal params
    out_vars = {}
    coords = {"lat": ys, "lon": xs}

    # Annual diurnal & autocorr
    amp_a, ph_a = fit_diurnal(wspd, hours_of_day)
    ac_a = lag1_autocorr(wspd)
    era5_mean_annual = float(np.nanmean(wspd))
    print(f"  annual: era5_mean={era5_mean_annual:.2f}  amp={amp_a:.2f}  phase={ph_a:.1f}  ac={ac_a:.3f}")

    # GWA mean is the spatial pattern; assume the ERA5 box-mean ratio gives the
    # site-relative scaling vs the GWA pattern. Use GWA directly for spatial mean
    # (already calibrated against ERA5 in GWA's own production pipeline).
    mean_2d = mean

    # Apply 5-param formula for all 195 combos
    for T in THRESHOLDS:
        for H in HOURS:
            tag = f"t{T:.1f}_h{H}".replace(".", "_")
            out_vars[f"pct_{tag}_annual"] = (("lat", "lon"),
                calm_prob(mean_2d, k_arr, amp_a, ph_a, ac_a, T, H))
            for m in range(1, 13):
                mask = months == m
                if mask.sum() < 24:
                    continue
                wsm = wspd[mask]
                hsm = hours_of_day[mask]
                amp_m, ph_m = fit_diurnal(wsm, hsm)
                ac_m = lag1_autocorr(wsm)
                era5_mean_m = float(np.nanmean(wsm))
                # Scale GWA mean by month-to-annual ratio of ERA5 box mean
                ratio = era5_mean_m / max(era5_mean_annual, 0.1)
                mean_m = mean_2d * ratio
                out_vars[f"pct_{tag}_m{m:02d}"] = (("lat", "lon"),
                    calm_prob(mean_m, k_arr, amp_m, ph_m, ac_m, T, H))
        print(f"    finished t={T}")

    out_path = ROOT / "data/calm" / f"{slug}.nc"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = xr.Dataset(out_vars, coords=coords, attrs={
        "slug": slug,
        "lat": lat, "lon": lon,
        "model": "5-parameter Weibull+Markov; spatial=GWA 250m, temporal=ERA5 hourly box-mean",
    })
    enc = {v: {"zlib": True, "complevel": 4} for v in out.data_vars}
    out.to_netcdf(out_path, encoding=enc)
    print(f"[{slug}] → {out_path} ({out_path.stat().st_size // (1024**2)} MB, {len(out.data_vars)} vars)")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="+")
    args = ap.parse_args()
    for s in args.slugs:
        compute_site(s)


if __name__ == "__main__":
    main()
