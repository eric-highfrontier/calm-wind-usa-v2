# Calm Wind Mapper — US Spaceports edition

## Project overview
Sister project to `/Volumes/X10 Pro/calm-wind-mapper` (Iberia). Map-of-USA viewer
showing every FAA-licensed/federal/private launch site, with a high-resolution
calm-wind tile pyramid around each spaceport using the same Weibull+Markov
calm-fraction model as calm-winds-spain.netlify.app.

Live (Phase A shipped): https://calm-winds-usa.netlify.app
Netlify site_id: d52d6b22-6c40-4198-9bb3-ec6d2df1f0d9
Plan file: ~/.claude/plans/hidden-greeting-nygaard.md

## Architecture
Two-tier viewer, single Netlify site `calm-winds-usa`:
- **Top map** (`index.html`): markers for every spaceport. Coarse CONUS+AK calm
  overlay (annual t2.0_h2) at z3-z7. Click marker → side-card with photo,
  license, activity paragraph; "Open high-resolution wind map" link.
- **Per-site** (`site.html?site=<slug>`): identical month/threshold/hours
  controls and GWA colormap as the Spain viewer. Tiles served from
  `tiles/<slug>/<period>/t<thresh>_h<hours>/{z}/{x}/{y}.png`.

## Data sources
| What | Where | Why |
|---|---|---|
| ERA5 hourly 100m winds | Google Public Datasets ARCO zarr (`gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3`) | CDS API kept rejecting bbox requests with "cost limits exceeded"; ARCO is the analysis-ready cube of the same dataset, free, anonymous, no per-request cap |
| GWA 250m mean wind, Weibull A/k | `globalwindatlas.info/api/gis/country/USA/{layer}/100` | speedup-ratio calibration of ERA5 → ~250m |
| USGS 3DEP DEM 10m (CONUS) | `s3://prd-tnm/StagedProducts/Elevation/13/TIFF/...` | per-spaceport terrain refinement, 10m → ~5m via cubic upsampling |
| USGS 3DEP DEM 60m (Alaska) | `s3://prd-tnm/StagedProducts/Elevation/2/TIFF/...` | only 2-arc-second covers Kodiak (and most of AK) — 1/3-arc-sec stops at CONUS |
| Site photos | Esri World Imagery tiles, stitched 3×3 | no API key required, attribution-only |

## Pipeline
```
scripts/
  fetch_era5_arco.py            # ARCO ERA5 — CONUS + per-site
  fetch_era5_conus_coarse.py    # legacy CDS path (kept as fallback)
  fetch_era5_per_site.py        # legacy CDS path (kept as fallback)
  fetch_gwa_us.py               # GWA US 250m rasters
  fetch_dem_per_site.py         # USGS 3DEP per-site clipper
  fetch_site_photos.py          # Esri tile stitcher → photos/
  compute_calm.py               # 195-combo (annual + monthly × 5 thresh × 3 hr)
  render_tiles.py               # GWA-colormap PNG tile pyramid
```

## Deployment
- Netlify site: `calm-winds-usa` (id `d52d6b22-6c40-4198-9bb3-ec6d2df1f0d9`)
- Deploy command:
  `netlify deploy --dir=deploy_real_us --site=d52d6b22-6c40-4198-9bb3-ec6d2df1f0d9 --prod --no-build`
- Same gotcha as Spain: real files only, no symlinks
- Cloud Run tile-server (Phase C, NOT YET): `calm-tiles-usa` in `us-central1`

## Spaceport set (20)
See `data/sites.json` for the canonical list. Slug is the URL key for both
photos and tile dirs.

## Phase status
- **A done** (May 8, 2026): scaffold, sites.json with all 20 sites, photos,
  top-map, deployed.
- **B in progress**: CONUS+AK 2023 hourly downloading from ARCO (~30-60 min);
  compute_calm + render_tiles scripts ready.
- **C pending**: per-site Granada-style 5-parameter Weibull+Markov.
- **D pending**: methodology page, KMZ export.

## Key code reuse from `/Volumes/X10 Pro/calm-wind-mapper/`
- The 11-stop GWA colormap (`render_tiles.py:CMAP`) — identical RGB stops.
- The numba `calm_pct()` (compute_calm.py) — same algorithm as Spain's
  `compute_calm.py` `detect_calm_runs()`, simplified to single output.
- The Leaflet/CalmDataLayer scaffold (deploy_real_us/index.html) — derived
  from Spain's deploy_real/index.html with marker layer added.

## Known gotchas
- ARCO ERA5 uses 0-360 longitude (US sites need normalisation, handled in
  `compute_calm.py`).
- CDS API new endpoint requires UUID-format PAT in `~/.cdsapirc`; the user's
  cdsapirc is ALREADY correctly configured but every CDS request hits "cost
  limits exceeded" for any reasonable bbox+year combo. ARCO is the workaround.
- `gdalwarp` must be on PATH for `fetch_dem_per_site.py` (`brew install gdal`).
