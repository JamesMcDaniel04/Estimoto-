"""Run bounded production-directory checks without creating customer records.

Run in the deployed service environment: python -m scripts.check_places.
Uses the normal shared quotas and emits only public search evidence.
"""
import argparse
import json
from types import SimpleNamespace

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.discovery import search

CASES = [('10001', 'Toyota', ''), ('80229', 'Audi', 'Bluewater'),
         ('90012', 'Honda', ''), ('60601', 'Ford', ''), ('98101', 'Subaru', '')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect-sha', required=True)
    args = parser.parse_args()
    settings = Settings(worker_enabled=False)
    if settings.source_sha != args.expect_sha:
        raise SystemExit('Deployed source does not match the requested verification commit.')
    if not settings.discovery_enabled or not settings.places_enabled or not settings.google_places_api_key:
        raise SystemExit('Google Places is not enabled and configured on this deployment.')
    app = create_app(settings)
    request = SimpleNamespace(app=app)
    customer = SimpleNamespace(id='qa-directory-readonly-no-customer', demo=False)
    passed = True
    try:
        for postal, make, query in CASES:
            with app.state.session_factory() as db:
                result = search(db, request, customer, postal,
                    SimpleNamespace(id='qa-directory-readonly-no-vehicle', make=make), query=query)
            google = [r for r in result['providers'] if r['source'] == 'google_places']
            ok = result['status'] == 'ready' and result.get('directory_provider') == 'google_places' and bool(google)
            passed = passed and ok
            print(json.dumps({'postal_code': postal, 'make': make, 'query': query, 'passed': ok,
                'status': result['status'], 'directory_provider': result.get('directory_provider'),
                'google_results': len(google), 'first_names': [r['name'] for r in google[:3]],
                'source_sha': settings.source_sha}), flush=True)
    finally:
        app.state.engine.dispose()
    if not passed:
        raise SystemExit('One or more live coverage checks failed; do not report nationwide coverage as verified.')


if __name__ == '__main__':
    main()
