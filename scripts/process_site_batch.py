#!/usr/bin/env python3
"""End-to-end pipeline for a list of spaceports:
  compute_calm_5param.py  → data/calm/<slug>.nc
  render_all_combos.py    → deploy_real_us/tiles/<slug>/...

Reuses whatever per-site ERA5 is already on disk; falls back to CONUS-coarse
slice (1 cell at the site's location) when the per-site CDS download hasn't
delivered yet. The compute step works either way; the resolution improvement
comes from the GWA spatial pattern, not the ERA5 spatial pattern.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compute_calm_5param import compute_site as compute  # noqa: E402
from render_all_combos import render  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="+", help="(or 'all' for every site in sites.json)")
    ap.add_argument("--z-min", type=int, default=7)
    ap.add_argument("--z-max", type=int, default=11)
    ap.add_argument("--skip-compute", action="store_true",
                    help="reuse existing data/calm/<slug>.nc")
    args = ap.parse_args()

    if args.slugs == ["all"]:
        sites = json.loads((ROOT / "data" / "sites.json").read_text())["sites"]
        slugs = [s["slug"] for s in sites]
    else:
        slugs = args.slugs

    for slug in slugs:
        calm_nc = ROOT / "data" / "calm" / f"{slug}.nc"
        out_root = ROOT / "deploy_real_us" / "tiles" / slug
        if not calm_nc.exists() or not args.skip_compute:
            print(f"\n=== compute {slug} ===")
            try:
                compute(slug)
            except Exception as e:
                print(f"  ✗ compute failed: {e}", file=sys.stderr)
                continue
        print(f"\n=== render {slug} ({args.z_min}-{args.z_max}) ===")
        try:
            render(slug, calm_nc, out_root, args.z_min, args.z_max)
        except Exception as e:
            print(f"  ✗ render failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
