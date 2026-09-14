# Launch audit follow-up

The September 13 audit examined Plus build 7 (`ebb7f47275b018f276744322bbb2c191438e4f7a`). This record tracks its 17 findings against the build-8 candidate. Source fixes, local tests, deployed behavior and provider approval are separate evidence. Final delivery is recorded in [release status](../release-status.md) and [mobile release](../mobile-release.md).

| Finding | Resolution in the candidate | Evidence / remaining check |
| --- | --- | --- |
| H1: main behind production | Bring `main` forward to this tested candidate; README uses the permanent Android URL. | Record remote branch and live source after publishing; do not force-push. |
| H2: hosted CI billing lock | Added missing capture and PostgreSQL jobs plus discovery/calendar socket checks; added a local release gate. | **External block:** GitHub annotations say the account is locked for billing. Local runs do not establish hosted CI success. Account owner must resolve billing and rerun Actions. |
| H3: pure-Dart socket no longer compiles | Repository APIs import platform-free pending-operation types; UI still uses its native storage adapters. | `scripts/smoke_api.py --flutter-client` passes the real HTTP Dart client and restart checks. |
| H4: capture tests omitted | `build_capture.sh` runs tests before bundling; CI has a capture-web job. | All 19 Vitest tests and TypeScript/Vite build pass locally. Every live web build uses this script. |
| H5: contradictory docs | Reconciled backend README, API contract and launch record with live submission, capture, images, valuation, scheduling and discovery. | Historical build evidence stays dated; candidate claims do not imply deployment. |
| M1: public production docs | Production disables `/docs`, `/redoc`, `/openapi.json`; development keeps them. | `test_production_surface.py`; verify live 404 after deployment. |
| M2: missing-record dead ends | Unavailable screens retain an app bar/back action; deleted records have accurate copy; guided photos handle a missing estimate. | `audit_navigation_test.dart` exercises navigation and deleted-record cases. |
| M3: demo phone scheduling has no call | Authorized phone-only draft becomes `call_required` with a validated call URI. | Regression checks consent and exact mocked `tel:` launch. No real shop is called by tests. |
| M4: default calendar UTC | New connections start without a zone; first setup suggests a validated device IANA zone. Existing saved zones, including UTC, stay intact. Demo uses Denver. | Flutter/backend calendar regressions cover first setup, reconnect and saved choices. Native channel compilation and device rendering remain release checks. |
| M5: every read rechecks Auth | Per-app pooled HTTP client and bounded positive read cache, with duplicate concurrent checks coalesced. Writes always verify upstream and invalidate reads. | Auth cache regressions cover expiry, revocation, errors, capacity, concurrency and app isolation. See tradeoff below. |
| M6: missing web frame/security headers | Production sets HSTS and frame protection; guided capture keeps same-origin embedding policy. | Production surface tests; verify actual response headers after deployment. |
| M7: overly broad Estibot promise | Prompt names supported estimate/routine-care/matching/scheduling topics and explains diagnostic limits. | Flutter UI tests; no claim of general diagnostic AI. |
| L1: malformed email called empty | Separate empty-address and invalid-address messages. | Welcome-screen validation regressions. |
| L2: demo valuation disabled | Synthetic VIN and fixed fictional result let the demo show the valuation layout. | Labeled as a local sample, not a CarsXE result; no provider call and no claim it values that car. |
| L3: inaccurate WebView resume doc | Integration docs describe pause, reload and fresh handshake on resume. | Checked against the native host; reserved resume RPC is distinguished. |
| L4: stale web shell | Entry HTML, bootstrap, service worker, main bundle and version/manifest responses require revalidation. | Production surface tests; live headers checked after deployment. |
| L5: 34 skipped integration cases | New isolated PostgreSQL 17.6 plus actual original bridge source exercised every skipped case. | Initial source snapshot: 369 passed, zero skipped; final clean candidate uses the integrated release gate below. |

## Authentication capacity tradeoff

Only upstream-confirmed, non-anonymous identities are cached. Keys are SHA-256 token hashes; raw tokens, user metadata, errors and negative responses are not retained. GET/HEAD cache entries last at most 15 seconds from verification start and never beyond JWT expiry; monotonic and absolute clocks both bound reuse. Capacity is 1,024 identities and 64 in-flight checks per app. Mutations always reverify and invalidate the token's read cache before and after verification. An upstream-revoked token can therefore remain readable for the remainder of that brief read window; it cannot use the cache to authorize an edit.

This reduces duplicate authentication calls; it is not a load-test result or proof of multi-machine readiness. Private uploads still use the current mounted volume. Wider scaling needs a shared storage/worker plan before adding replicas.

## Reproduce a complete local release gate

Use a **new disposable local PostgreSQL database**, with test-only `anon` and `authenticated` roles, and a local checkout of the original Estimoto backend. The tests create/reset their test schema. Never supply a production database URL.

Set `PLUS_TEST_POSTGRES_URL`, `CALENDAR_TEST_POSTGRES_URL` and `DISCOVERY_TEST_POSTGRES_URL` to that disposable database's `postgresql+psycopg://` URL. Set `ESTIMOTO_BRIDGE_BACKEND` to the original backend directory and `ESTIMOTO_BRIDGE_PYTHON` to its prepared Python environment. No bridge production key is needed.

From the clean Plus candidate, run:

```sh
python3 scripts/check_release.py --integration --output /tmp/plus-release-checks-unique
```

The gate records its source SHA, log hashes, return codes and backend skip count, then rejects source changes during the run. It runs backend pytest, Flutter analysis/tests, capture-web tests/build, API plus pure-Dart socket checks, discovery socket checks and calendar socket checks. `--integration` rejects any skipped backend test. Keep raw logs private until reviewed; copy sanitized results into release evidence. Stop and remove only the temporary PostgreSQL cluster created for that run.

## Checks that source tests cannot establish

- Real mailbox delivery plus code entry for `hello@estimoto.io` on web and Android still needs actual inbox/device evidence. Admin-generated synthetic sign-in codes do not prove email delivery.
- GitHub's billing lock is an account-level issue. The latest inspected failed build-7 run was `34806833579`; its Flutter check annotation reported that no job started because of billing.
- Apple's existing Plus external beta review and Google Calendar provider enablement remain separate gates; neither is established by group attachment or local tests.
- Physical-device camera quality, real shop acceptance, and customer scheduling delivery remain distinct from emulators and isolated bridge fixtures.
