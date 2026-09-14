#!/usr/bin/env python3
"""Warm a small public ZIP directory cache; no customer identity or shop sends."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.discovery_cache import public_directory, zip_location
from estimoto_plus.postal import canonical_zip


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postal-code', action='append', required=True, help='US ZIP, at most five per run')
    args = parser.parse_args()
    zips = list(dict.fromkeys(canonical_zip(value) for value in args.postal_code))
    if not all(zips) or len(zips) > 5:
        parser.error('Use one to five valid US ZIP codes.')
    settings = Settings()
    if not settings.discovery_enabled:
        parser.error('Discovery must be enabled in this service environment.')
    app = create_app(settings)
    available = True
    for postal in zips:
        center, geo_status, _ = zip_location(app.state.session_factory, None, postal)
        data, status, checked = (None, 'unavailable', None)
        if center and geo_status == 'ready':
            data, status, checked = public_directory(app.state.session_factory, None, postal, center['point'], settings)
        print(json.dumps({'postal_code': postal, 'geocoding_status': geo_status, 'directory_status': status,
                          'cached_public_listings': len((data or {}).get('listings', [])),
                          'checked_at': checked.isoformat() if checked else None}), flush=True)
        available = available and status == 'ready'
    return 0 if available else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        # Environment/DB/provider errors must not print credentials or rows.
        print('Public directory warmup could not finish. Inspect protected service diagnostics.', file=sys.stderr)
        raise SystemExit(2)
