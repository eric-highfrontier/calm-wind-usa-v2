#!/usr/bin/env python3
"""KMZ export for each spaceport — opens in Google Earth.

For each site we emit a single KMZ containing the annual t<2/h≥2 calm grid
as a GroundOverlay (PNG with bbox), plus a placemark at the site, plus the
license/activity metadata in the description balloon. Default rendering settings
match the web viewer (GWA colormap, 75% opacity).

Output: deploy_real_us/kmz/<slug>.kmz
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from render_tiles import colorize  # noqa: E402

SITES = ROOT / "data/sites.json"
CALM_DIR = ROOT / "data/calm"
OUT_DIR = ROOT / "deploy_real_us" / "kmz"

# Default exported combo
PERIOD = "annual"
THRESH = "2_0"
HOURS = 2


def kml_for_site(site: dict, png_relpath: str, north: float, south: float,
                 east: float, west: float) -> str:
    activity_html = (site["activity"]
                     .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
<name>{site['name']} — Calm Wind Map</name>
<description><![CDATA[
<b>{site['name']}</b><br>
{site['state']} · {site['lat']:.4f}°, {site['lon']:.4f}°<br>
<i>{site['license']['number']} · {site['license']['type']} · since {site['license'].get('issued', '—')}</i><br>
<b>Operator:</b> {site['operator']}<br><br>
{activity_html}<br><br>
<i>Calm overlay: % of days with calm window of {HOURS}h below 2.0 m/s, annual.</i>
]]></description>
<GroundOverlay>
<name>Calm Wind (annual, t&lt;2 m/s, h≥2)</name>
<color>bfffffff</color>
<Icon><href>{png_relpath}</href></Icon>
<LatLonBox>
<north>{north}</north><south>{south}</south><east>{east}</east><west>{west}</west>
</LatLonBox>
</GroundOverlay>
<Placemark>
<name>{site['name']}</name>
<Point><coordinates>{site['lon']},{site['lat']},0</coordinates></Point>
</Placemark>
</Document>
</kml>"""


def export_site(site: dict) -> Path | None:
    slug = site["slug"]
    nc = CALM_DIR / f"{slug}.nc"
    if not nc.exists():
        print(f"[skip] {slug}: no calm.nc")
        return None
    ds = xr.open_dataset(nc)
    var = f"pct_t{THRESH}_h{HOURS}_{PERIOD}"
    if var not in ds.data_vars:
        print(f"[skip] {slug}: var {var} missing")
        return None
    arr = ds[var].values
    lat = ds["lat"].values
    lon = ds["lon"].values
    # Render the full-resolution PNG (no resampling, just colormap)
    rgba = colorize(arr if lat[0] < lat[-1] else arr[::-1])
    img = Image.fromarray(rgba, "RGBA")
    # Resize to 2048×2048 max for KMZ-friendly file size
    if max(img.size) > 2048:
        scale = 2048 / max(img.size)
        new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
        img = img.resize(new_size, Image.BILINEAR)
    png_buf = io.BytesIO()
    img.save(png_buf, "PNG", optimize=True)
    png_bytes = png_buf.getvalue()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{slug}.kmz"
    north, south = float(lat.max()), float(lat.min())
    east, west = float(lon.max()), float(lon.min())
    kml = kml_for_site(site, "calm.png", north, south, east, west)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml)
        zf.writestr("calm.png", png_bytes)
    print(f"[ok] {slug} → {out.name} ({out.stat().st_size//1024} KB)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", help="(default: all)")
    args = ap.parse_args()
    sites = json.loads(SITES.read_text())["sites"]
    if args.slugs:
        sites = [s for s in sites if s["slug"] in args.slugs]
    for s in sites:
        export_site(s)


if __name__ == "__main__":
    main()
