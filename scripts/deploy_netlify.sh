#!/bin/bash
# Build the tiles_index.json and push deploy_real_us/ to Netlify production.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -u scripts/build_tiles_index.py
netlify deploy --dir=deploy_real_us \
  --site=d52d6b22-6c40-4198-9bb3-ec6d2df1f0d9 \
  --prod --no-build
