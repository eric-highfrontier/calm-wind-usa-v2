#!/usr/bin/env python3
"""Emit deploy_real_us/data/tiles_index.json — which slugs have tiles available,
plus the count of rendered combos per slug.

Front-end uses this to badge markers and enable/disable the "Open wind map" CTA.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "data" / "sites.json"
TILES = ROOT / "deploy_real_us" / "tiles"
OUT = ROOT / "deploy_real_us" / "data" / "tiles_index.json"


def main() -> None:
    sites = json.loads(SITES.read_text())["sites"]
    out = {"slugs": {}, "conus_overlay": (TILES / "conus" / "annual" / "t2_0_h2").exists()}
    for s in sites:
        slug = s["slug"]
        slug_dir = TILES / slug
        if not slug_dir.exists():
            continue
        # count combo dirs (period/threshold)
        n_combos = 0
        n_tiles = 0
        for period_dir in slug_dir.iterdir():
            if not period_dir.is_dir():
                continue
            for combo_dir in period_dir.iterdir():
                if combo_dir.is_dir() and any(combo_dir.rglob("*.png")):
                    n_combos += 1
        n_tiles = sum(1 for _ in slug_dir.rglob("*.png"))
        if n_combos > 0:
            out["slugs"][slug] = {"combos": n_combos, "tiles": n_tiles}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"wrote {OUT}")
    print(f"  conus_overlay: {out['conus_overlay']}")
    for s, v in out["slugs"].items():
        print(f"  {s}: {v['combos']} combos / {v['tiles']} tiles")


if __name__ == "__main__":
    main()
