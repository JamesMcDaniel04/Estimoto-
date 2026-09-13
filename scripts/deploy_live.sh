#!/bin/sh
# Deploy the exact clean source together with a freshly built live web client.
set -eu
PLUS_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PLUS_ROOT"
sh scripts/build_live.sh web
PLUS_SHA=$(git rev-parse HEAD)
fly deploy --app estimoto-plus-api --config fly.toml --ha=false --remote-only --yes --build-arg SOURCE_SHA="$PLUS_SHA" "$@"
python3 - "$PLUS_SHA" <<'PY'
import json
import sys
from urllib.request import urlopen
origin = 'https://estimoto-plus-api.fly.dev'
with urlopen(origin + '/version', timeout=20) as response:
    version = json.load(response)
if version.get('source_sha') != sys.argv[1]:
    raise SystemExit('Deployed source does not match the candidate.')
with urlopen(origin + '/ready', timeout=20) as response:
    readiness = json.load(response)
print('Verified deployed source:', version['source_sha'])
print('Ready at schema:', readiness['schema_revision'])
PY
