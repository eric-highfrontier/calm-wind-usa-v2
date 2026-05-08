#!/usr/bin/env python3
"""Download Global Wind Atlas (GWA) 250 m mean wind, Weibull A and k for the USA.

GWA serves country-bounded GeoTIFFs at ~250 m resolution at 100 m AGL. Endpoint:
    https://globalwindatlas.info/api/gis/country/{ISO3}/{layer}/{height}

We fetch:
    - mean-wind-speed (combined)
    - weibull-A
    - weibull-k
For ISO3=USA, height=100 (matches our 100 m wind level).

Output: data/gwa/gwa_usa_<layer>_100m.tif
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "gwa"

LAYERS = ["wind-speed", "combined-Weibull-A", "combined-Weibull-k"]
HEIGHTS = ["100"]
ISO3 = "USA"
URL = "https://globalwindatlas.info/api/gis/country/{iso}/{layer}/{height}"
UA = "calm-wind-usa/0.1 (z2i pipeline; jose.mariano@zero2infinity.space)"


def fetch(layer: str, height: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"gwa_{ISO3.lower()}_{layer.replace('-', '_')}_{height}m.tif"
    if out.exists() and out.stat().st_size > 1_000_000:
        print(f"[skip] {out.name} {out.stat().st_size//(1024**2)} MB")
        return out
    url = URL.format(iso=ISO3, layer=layer, height=height)
    print(f"[fetch] {layer} @ {height}m USA")
    req = Request(url, headers={"User-Agent": UA, "Accept": "image/tiff"})
    with urlopen(req, timeout=600) as r:
        body = r.read()
    out.write_bytes(body)
    print(f"  ✓ {out.name} {out.stat().st_size//(1024**2)} MB")
    return out


def main() -> None:
    for layer in LAYERS:
        for h in HEIGHTS:
            try:
                fetch(layer, h)
            except Exception as e:
                print(f"  ✗ {layer}@{h}m: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
