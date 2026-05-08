#!/usr/bin/env python3
"""Per-spaceport USGS 3DEP DEM fetcher.

Strategy:
  - CONUS sites: USGS 3DEP 1/3 arc-second (~10 m) GeoTIFFs from AWS S3 public bucket
        s3://prd-tnm/StagedProducts/Elevation/13/TIFF/<USGS_n##w###/USGS_13_n##w###.tif
        (1°×1° tiles, naming = SW corner integer lat/lon)
  - Alaska sites: 2 arc-second (~60 m) tiles
        s3://prd-tnm/StagedProducts/Elevation/2/TIFF/<USGS_n##w###/USGS_2_n##w###.tif

For each site we download the ≤4 USGS 1° tiles needed to cover the ±0.75° box,
mosaic them, clip to the bbox, and write a single GeoTIFF per site.

Output: data/dem/<slug>.tif  (cropped, EPSG:4326)
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "data" / "sites.json"
OUT = ROOT / "data" / "dem"
CACHE = ROOT / "data" / "dem" / "_cache"

UA = "calm-wind-usa/0.1 (z2i)"
HALF = 0.75


def tile_name(lat_deg: int, lon_deg: int, dataset: str) -> tuple[str, str]:
    """USGS naming: SW corner of 1° tile uses N{lat}W{lon} where lat is north of corner."""
    # 3DEP convention: tile name uses the *NW* corner — north lat, west lon (positive lon)
    # so the actual corners are (lat_deg+1, -lon_deg) for NW, etc. Our lat_deg is the
    # floor of the bbox lat. The tile that contains lat L has NW lat = ceil(L).
    # For lon: floor(lon_west) gives integer west lon; tile NW lon = ceil(-west) → for
    # western hemisphere the integer in name is |floor(west) + 1|.
    n = lat_deg + 1
    w = -lon_deg  # lon_deg is negative (W hem); -lon_deg is positive 1°-aligned west lon
    if dataset == "13":
        prefix = f"USGS_13_n{n:02d}w{w:03d}"
    else:
        prefix = f"USGS_2_n{n:02d}w{w:03d}"
    # Public layout: StagedProducts/Elevation/{ds}/TIFF/current/n##w###/USGS_{ds}_n##w###.tif
    s3_key = f"StagedProducts/Elevation/{dataset}/TIFF/current/n{n:02d}w{w:03d}/{prefix}.tif"
    return prefix, s3_key


def needed_tiles(lat: float, lon: float) -> list[tuple[int, int]]:
    south = math.floor(lat - HALF)
    north = math.floor(lat + HALF)
    west = math.floor(lon - HALF)
    east = math.floor(lon + HALF)
    return [(la, lo) for la in range(south, north + 1) for lo in range(west, east + 1)]


def download(s3_key: str) -> Path | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    fname = Path(s3_key).name
    out = CACHE / fname
    if out.exists() and out.stat().st_size > 1_000_000:
        return out
    url = f"https://prd-tnm.s3.amazonaws.com/{s3_key}"
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=300) as r:
            body = r.read()
    except Exception as e:
        print(f"  miss: {url} ({e})", file=sys.stderr)
        return None
    out.write_bytes(body)
    print(f"  pulled {fname} ({out.stat().st_size//(1024**2)} MB)")
    return out


def fetch_site(slug: str, lat: float, lon: float) -> Path | None:
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{slug}.tif"
    if out.exists() and out.stat().st_size > 5_000_000:
        print(f"[skip] {slug}")
        return out

    is_alaska = lat > 50  # 3DEP 1/3-arc-sec coverage stops at AK; use 2 arc-sec
    dataset = "2" if is_alaska else "13"
    tiles = needed_tiles(lat, lon)
    print(f"[{slug}] {len(tiles)} 1° tiles  dataset={dataset}")

    locals_ = []
    for la, lo in tiles:
        _, key = tile_name(la, lo, dataset)
        p = download(key)
        if p:
            locals_.append(p)
    if not locals_:
        print(f"[{slug}] FAIL no tiles found", file=sys.stderr)
        return None

    bbox = (lon - HALF, lat - HALF, lon + HALF, lat + HALF)  # west, south, east, north

    if shutil.which("gdalwarp"):
        cmd = [
            "gdalwarp", "-q", "-overwrite",
            "-te", *map(str, bbox),
            "-t_srs", "EPSG:4326",
            "-r", "bilinear",
            "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES",
            *map(str, locals_), str(out),
        ]
        subprocess.run(cmd, check=True)
    else:
        # Pure-rasterio fallback: merge tiles, then crop window
        import rasterio
        from rasterio.merge import merge
        from rasterio.windows import from_bounds
        srcs = [rasterio.open(p) for p in locals_]
        merged, transform = merge(srcs)
        merged_meta = srcs[0].meta.copy()
        # Crop to bbox
        west, south, east, north = bbox
        from rasterio.transform import Affine, rowcol
        col_w, row_n = ~transform * (west, north)
        col_e, row_s = ~transform * (east, south)
        col_w, col_e = sorted((int(col_w), int(col_e)))
        row_n, row_s = sorted((int(row_n), int(row_s)))
        clip = merged[0, row_n:row_s, col_w:col_e]
        new_transform = transform * Affine.translation(col_w, row_n)
        merged_meta.update({
            "count": 1, "height": clip.shape[0], "width": clip.shape[1],
            "transform": new_transform, "compress": "DEFLATE", "tiled": True,
        })
        with rasterio.open(out, "w", **merged_meta) as dst:
            dst.write(clip[None])
        for s in srcs:
            s.close()
    print(f"  ✓ {out.name} {out.stat().st_size//(1024**2)} MB")
    return out


def main() -> None:
    sites = json.loads(SITES.read_text())["sites"]
    if len(sys.argv) > 1:
        sel = set(sys.argv[1:])
        sites = [s for s in sites if s["slug"] in sel]
    for s in sites:
        try:
            fetch_site(s["slug"], s["lat"], s["lon"])
        except Exception as e:
            print(f"[{s['slug']}] FAIL: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
