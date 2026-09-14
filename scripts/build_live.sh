#!/bin/sh
# Build the real customer app with explicit public-only runtime configuration.
set -eu
PLUS_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PLUS_ROOT"
PLUS_TARGET=${1:-all}
case "$PLUS_TARGET" in web|mobile|all) ;; *) echo 'Usage: build_live.sh [web|mobile|all]' >&2; exit 2 ;; esac
if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
  echo 'Commit the candidate before producing live artifacts.' >&2
  exit 1
fi
python3 - <<'PY'
import json
from pathlib import Path
from urllib.parse import urlparse
p = Path('app/config/local.json')
config = json.loads(p.read_text())
expected = {'PLUS_API_URL', 'SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'PLUS_DEMO'}
if set(config) != expected or str(config['PLUS_DEMO']).lower() != 'false':
    raise SystemExit('Live config must contain only the four supported public fields, with PLUS_DEMO=false.')
for key in ('PLUS_API_URL', 'SUPABASE_URL'):
    u = urlparse(config[key])
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('', '/'):
        raise SystemExit('Live origins must be plain HTTPS origins.')
if not config['SUPABASE_PUBLISHABLE_KEY'].startswith('sb_publishable_'):
    raise SystemExit('Use a Supabase publishable key, never a secret or service role key.')
print('Live configuration validated; no private provider keys enter the app.')
PY
PLUS_SHA=$(git rev-parse HEAD)
cd app
flutter pub get --enforce-lockfile
PLUS_VERSION_NAME=$(sed -n 's/^version: \([0-9.]*\)+.*/\1/p' pubspec.yaml)
PLUS_BUILD_NUMBER=$(sed -n 's/^version: [0-9.]*+\([0-9]*\).*/\1/p' pubspec.yaml)
if [ "$PLUS_TARGET" = web ] || [ "$PLUS_TARGET" = all ]; then
  flutter build web --release --no-pub --dart-define-from-file=config/local.json --dart-define=SOURCE_SHA="$PLUS_SHA" --dart-define=PLUS_VERSION_NAME="$PLUS_VERSION_NAME" --dart-define=PLUS_BUILD_NUMBER="$PLUS_BUILD_NUMBER"
  sh "$PLUS_ROOT/scripts/build_capture.sh"
  mkdir -p "$PLUS_ROOT/app/build/web/capture"
  cp -R "$PLUS_ROOT/capture-web/dist/." "$PLUS_ROOT/app/build/web/capture/"
fi
if [ "$PLUS_TARGET" = mobile ] || [ "$PLUS_TARGET" = all ]; then
  test -f android/key.properties || { echo 'Configure owner-controlled Android release signing first.' >&2; exit 1; }
  rm -f "$PLUS_ROOT/app/build/android-build-receipt.json"
  flutter build ipa --release --no-pub --export-options-plist=ios/ExportOptions.plist --dart-define-from-file=config/local.json --dart-define=SOURCE_SHA="$PLUS_SHA" --dart-define=PLUS_VERSION_NAME="$PLUS_VERSION_NAME" --dart-define=PLUS_BUILD_NUMBER="$PLUS_BUILD_NUMBER"
  flutter build apk --release --no-pub --dart-define-from-file=config/local.json --dart-define=SOURCE_SHA="$PLUS_SHA" --dart-define=PLUS_VERSION_NAME="$PLUS_VERSION_NAME" --dart-define=PLUS_BUILD_NUMBER="$PLUS_BUILD_NUMBER"
  flutter build appbundle --release --no-pub --dart-define-from-file=config/local.json --dart-define=SOURCE_SHA="$PLUS_SHA" --dart-define=PLUS_VERSION_NAME="$PLUS_VERSION_NAME" --dart-define=PLUS_BUILD_NUMBER="$PLUS_BUILD_NUMBER"
  cd "$PLUS_ROOT"
  python3 backend/scripts/write_android_build_receipt.py --source-sha "$PLUS_SHA"
fi
printf 'Live %s artifacts built from %s. Verify identities, signatures and served hashes before distribution.\n' "$PLUS_TARGET" "$PLUS_SHA"
