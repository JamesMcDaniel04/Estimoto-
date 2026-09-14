#!/bin/sh
# Build the explicitly labeled customer demo beta; this does not upload it.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ -n "$(git status --porcelain -- app scripts/build_beta.sh)" ]; then
  echo 'Commit the app and build script before producing release artifacts.' >&2
  exit 1
fi
if [ ! -f app/android/key.properties ]; then
  echo 'Configure app/android/key.properties with the owner-controlled release keystore.' >&2
  exit 1
fi
git rev-parse HEAD
cd app
flutter pub get --enforce-lockfile
PLUS_VERSION_NAME=$(sed -n 's/^version: \([0-9.]*\)+.*/\1/p' pubspec.yaml)
PLUS_BUILD_NUMBER=$(sed -n 's/^version: [0-9.]*+\([0-9]*\).*/\1/p' pubspec.yaml)
flutter build ipa --release --no-pub --export-options-plist=ios/ExportOptions.plist --dart-define=PLUS_DEMO=true --dart-define=PLUS_VERSION_NAME="$PLUS_VERSION_NAME" --dart-define=PLUS_BUILD_NUMBER="$PLUS_BUILD_NUMBER"
flutter build apk --release --no-pub --dart-define=PLUS_DEMO=true --dart-define=PLUS_VERSION_NAME="$PLUS_VERSION_NAME" --dart-define=PLUS_BUILD_NUMBER="$PLUS_BUILD_NUMBER"
flutter build appbundle --release --no-pub --dart-define=PLUS_DEMO=true --dart-define=PLUS_VERSION_NAME="$PLUS_VERSION_NAME" --dart-define=PLUS_BUILD_NUMBER="$PLUS_BUILD_NUMBER"
flutter build web --no-pub --dart-define=PLUS_DEMO=true --dart-define=PLUS_VERSION_NAME="$PLUS_VERSION_NAME" --dart-define=PLUS_BUILD_NUMBER="$PLUS_BUILD_NUMBER"
echo 'Built demo beta artifacts. Verify embedded identities, signing and hashes before distribution.'
