#!/bin/sh
# One command for a Plus Android GitHub release and the permanent download link.
set -eu
PLUS_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PLUS_ROOT"
export PYTHONPATH="$PLUS_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
exec "$PLUS_ROOT/backend/.venv/bin/python" "$PLUS_ROOT/backend/scripts/publish_android_release.py" "$@"
