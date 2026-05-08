#!/usr/bin/env python3
"""Download a satellite tile of every spaceport via Esri World Imagery (free).

Output: deploy_real_us/photos/<slug>.jpg

Esri World Imagery is freely accessible without an API key for tile-style use
with the standard "© Esri, Maxar, Earthstar Geographics, and the GIS User
Community" attribution, which we surface in the viewer. We stitch 2×2 tiles at
zoom 12 (≈10–15 km wide) for federal ranges, z13 (≈5–7 km) for medium sites,
and z14 (≈2–3 km) for tight runway/pad crops.
"""
from __future__ import annotations

import json
import math
import sys
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "data" / "sites.json"
OUT = ROOT / "deploy_real_us" / "photos"

ZOOM = {
    "vandenberg-sfb": 12,
    "cape-canaveral-sfs": 12,
    "kennedy-space-center": 12,
    "wallops-flight-facility": 12,
    "mid-atlantic-regional-spaceport": 13,
    "pacific-spaceport-alaska": 13,
    "spaceport-america": 12,
    "blue-origin-launch-site-one": 12,
    "starbase": 14,
    "spaceport-camden": 13,
    "huntsville-international": 13,
    "midland-air-space-port": 12,
    "oklahoma-air-space-port": 13,
    "colorado-air-space-port": 13,
    "houston-spaceport": 13,
    "cecil-air-space-port": 13,
    "space-coast-regional": 13,
    "space-florida-lc46": 14,
    "space-florida-launch-landing-facility": 13,
    "mojave-air-space-port": 13,
}
DEFAULT_ZOOM = 13
TILE = 256
GRID = 3  # 3×3 → 768×768 px crop centred on site
URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
UA = "calm-wind-usa/0.1 (z2i poster pipeline; jose.mariano@zero2infinity.space)"


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[float, float]:
    lat_rad = math.radians(lat)
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def get_tile(z: int, x: int, y: int) -> Image.Image:
    url = URL.format(z=z, x=x, y=y)
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as r:
        return Image.open(BytesIO(r.read())).convert("RGB")


def fetch(slug: str, lat: float, lon: float) -> Path:
    z = ZOOM.get(slug, DEFAULT_ZOOM)
    fx, fy = lonlat_to_tile(lon, lat, z)
    cx, cy = int(fx), int(fy)
    half = GRID // 2
    canvas = Image.new("RGB", (TILE * GRID, TILE * GRID))
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            tile = get_tile(z, cx + dx, cy + dy)
            canvas.paste(tile, ((dx + half) * TILE, (dy + half) * TILE))
    # crop to a 700×440 frame centred on exact site (sub-pixel offset)
    px = (fx - (cx - half)) * TILE
    py = (fy - (cy - half)) * TILE
    W, H = 700, 440
    left, top = int(px - W / 2), int(py - H / 2)
    crop = canvas.crop((left, top, left + W, top + H))
    out_path = OUT / f"{slug}.jpg"
    crop.save(out_path, "JPEG", quality=82, optimize=True)
    print(f"[ok] {slug:42s} z{z} → {out_path.stat().st_size // 1024} KB")
    return out_path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sites = json.loads(SITES.read_text())["sites"]
    for s in sites:
        try:
            fetch(s["slug"], s["lat"], s["lon"])
        except Exception as e:
            print(f"[FAIL] {s['slug']}: {e}", file=sys.stderr)
    print(f"done — {len(sites)} sites")


if __name__ == "__main__":
    main()
