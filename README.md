# Calm Wind Map — US Spaceports

Mapa de USA con los 20 spaceports activos y, alrededor de cada uno, un mapa de probabilidad de viento calmo a alta resolución.

**Live:** https://calm-winds-usa.netlify.app

Hermano del proyecto España: https://calm-winds-spain.netlify.app

## Qué hay aquí

| Carpeta | Contenido |
|---|---|
| `scripts/` | 12 scripts del pipeline (descarga, cómputo, render, deploy, KMZ) |
| `data/sites.json` | Las 20 spaceports con coordenadas, número de licencia FAA, fecha de emisión, operador, párrafo de actividad real |
| `data/calm/<slug>.nc` | NetCDFs de probabilidad de calma por spaceport, 195 combos cada uno (anual + 12 meses × 5 umbrales × 3 duraciones) |
| `data/gwa/` | 3 GeoTIFFs USA del Global Wind Atlas a 250 m: mean wind, Weibull A, Weibull k |
| `data/dem/` | DEMs USGS 3DEP recortados por spaceport (10 m CONUS, 60 m Alaska) |
| `data/era5/` | NetCDFs horarios u100/v100/T2m de ERA5, 2023 a nivel CONUS, 2020-2023 a nivel per-site |
| `deploy_real_us/` | Frontend Leaflet + tile pyramid + photos + KMZs. Lo que sube a Netlify. |
| `CLAUDE.md` | Documentación interna del pipeline |

## Cómo correr una iteración

```bash
cd /Volumes/X10\ Pro/calm-wind-usa  # o donde lo descomprimas
python3 scripts/compute_calm_5param.py <slug>
python3 scripts/render_all_combos.py <slug> --z-min 7 --z-max 11
python3 scripts/build_tiles_index.py
python3 scripts/build_site_stats.py
bash scripts/deploy_netlify.sh
```

## Modelo (5 parámetros por píxel)

```
mean       — viento medio anual (de GWA)
k          — forma de Weibull (de GWA)
diurnal_amp — amplitud del ciclo diurno (de ERA5 horario)
diurnal_phase — hora UTC del mínimo diurno (de ERA5)
autocorr   — persistencia lag-1 (de ERA5)

P(viento_h < T)        = 1 - exp(-(T/c)^k)  con c = wind(h)/Γ(1+1/k)
wind(h)                = mean + diurnal_amp · cos(2π(h-diurnal_phase)/24)
P(H horas seguidas)    = P(1 hora) ^ (H/persistence_factor)
persistence_factor     = clip(1 + (autocorr-0.5)·0.6, 0.5, 1.5)
```

## Referencias

- Hersbach et al. 2020. The ERA5 global reanalysis. Q.J.R. Meteorol. Soc. 146(730):1999-2049.
- Davis et al. 2023. The Global Wind Atlas. Bulletin of the American Meteorological Society 104(8):E1507-E1525.
- Justus & Mikhail 1976. Height variation of wind speed and wind distributions statistics. GRL 3(5):261-264.
- Hennessey 1977. Some aspects of wind power statistics. J. Appl. Meteorol. 16(2):119-128.

## Plan completo

`~/.claude/plans/hidden-greeting-nygaard.md`
