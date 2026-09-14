#!/usr/bin/env bash
set -euo pipefail
PLUS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$PLUS_ROOT/capture-web/tools/shared_sources.py" verify
cd "$PLUS_ROOT/capture-web"
if [[ ! -x node_modules/.bin/vite ]]; then npm ci --ignore-scripts --legacy-peer-deps; fi
npm test
npm run build
