#!/usr/bin/env bash
set -euo pipefail
PLUS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/sync_capture_ui.sh ORIGINAL_ESTIMOTO_REPOSITORY_ROOT" >&2
  exit 2
fi
python3 "$PLUS_ROOT/capture-web/tools/shared_sources.py" sync "$1"
