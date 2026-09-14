# Guided customer release smoke

`backend/scripts/smoke_guided_customers.py` provides a bounded, repeatable proof
for the two protected synthetic customers. This change has **not run against
production**. The release owner must authorize the deployed revision before live
execution. The source reviewed during implementation was
`b08910b0d3a9b36ffd8196d2566db31a392527ae`; this report and the script are committed
together as the smoke-script change.

## Running it

From `/Users/jamesmcdaniel/Estimoto-/backend`:

```sh
.venv/bin/python scripts/smoke_guided_customers.py --self-test
.venv/bin/python scripts/smoke_guided_customers.py
```

The second command only validates local inputs. It made **zero network calls**
and returned `dry_inputs_valid` during implementation.

After the release owner authorizes the deployed source revision:

```sh
.venv/bin/python scripts/smoke_guided_customers.py --run-live --expected-sha=<full-deployed-source-sha>
```

Live mode is fixed to `https://estimoto-plus-api.fly.dev`. It checks `/version`
against the supplied 40-character revision and requires `/ready` before signing
in. It uses the normal Supabase password grant and verifies both returned user
IDs and emails against the protected receipt before creating test resources.
Stored access/refresh tokens are ignored and the original receipt is unchanged.

Inputs are read privately from:

- `~/.config/estimoto-plus/qa/2026-09-13-guided-customers.json`: exactly two unique
  accounts with roles `primary` and `foreign`, tagged
  `guided-customer-release-20260913`.
- `~/.config/estimoto-plus/service-env.json`: only `SUPABASE_URL` and
  `SUPABASE_PUBLISHABLE_KEY` are used. No database or bridge credentials are used.

Both inputs must be current-user-owned regular files with mode `0600`; symlink
files and oversized input are rejected. Supabase must be a fixed HTTPS
`*.supabase.co` origin, without a path, credentials, query, or fragment.

## Scope and receipts

Each run creates one uniquely named synthetic vehicle and private PDR draft for
each account. It never assumes either account is empty and never edits existing
vehicles, drafts, profiles, or favorites. A per-account cap of five smoke-marked
vehicles prevents unbounded rerun accumulation. A process lock prevents parallel
script runs from using these accounts.

The workflow verifies:

- A mobile-only PDR search around ZIP `80204`, radius 30 miles, returns at most
  100 listings across both response lists. Approximate distance, attribution,
  availability, truncation, and non-exhaustive coverage remain explicit.
- The exact participating Demolition source is a reachable `shop_visit`
  alternative, without inventing mobile coverage.
- A favorite is idempotent, readable only through its owned vehicle, and cannot
  be read, overwritten, or deleted by the other account. It does not appear in
  the other account's own favorites.
- Foreign-vehicle draft creation, foreign guided state/upload, anonymous/foreign
  photo reads, and attaching a foreign photo reference to an owned draft fail.
- A generated 80×80 JPEG is stored privately with an exact hash and
  `not_checked` framing status. It is uploaded through the reviewed legacy
  private route so this smoke does not invoke framing or OCR.
- VIN confirmation rejects invalid VIN characters, a stale photo hash, a foreign
  photo, and a stale saved-VIN comparison; explicit confirmation and its exact
  replay succeed only for the synthetic vehicle. The fixed VIN is test data,
  never OCR-derived or a claim about an actual vehicle.
- Both new estimates remain unsubmitted private drafts and neither account gains
  a service request.

Only the newly created favorite is removed, after reading back its exact owned
vehicle/source reference; deletion is then verified by another read. Accounts,
vehicles, drafts, and photo bytes are retained. There is no public draft deletion
API, so the script does not improvise database cleanup or account deletion.

Each run writes a mode-`0600` atomic, synced JSON journal inside mode-`0700`
`~/.config/estimoto-plus/qa/guided-smoke/`. It records exact account/resource IDs,
the unique run marker, mutation intentions, HTTP outcomes, synthetic image hash,
checks, and cleanup receipts. It contains no passwords or tokens. IDs are not
printed. Output and errors are redacted; HTTP error bodies are not preserved.

Every mutation intent is persisted before I/O. A timeout or uncertain response
stops the run and is journaled without automatic retry. Before rerunning after
an uncertain create, inspect the protected journal and match its unique run
marker in the synthetic account. Do not infer that a failed HTTP call rolled
back. This script deliberately provides no automatic recovery/delete mode.

The allowlist excludes estimate submission, service requests, shop outreach,
calendar actions, account deletion, OCR, guidance, and admin authentication.
The only guided-upload request is constrained to an expected foreign-owner
denial. API/auth clients disable redirects, proxy environment inheritance, and
compression. Bounds are 64 HTTP calls, a five-minute run deadline, a one-MiB
response limit, and explicit per-operation timeouts. HTTP debug logging is
disabled. Public directory cache refreshes may occur through the ordinary
server directory implementation; no shop contact or outbound delivery is asked
for by this script.

## Verification performed

The self-test ran **7 tests, all passed**. Its full workflow uses the actual Plus
FastAPI routes and a disposable SQLite database, with synthetic password Auth
and OSM/ZIP transports. Socket connections are explicitly forbidden. The run
completed **72 checks and 44 HTTP calls**, filtered **130 synthetic public
listings to 100 total returned listings**, and verified zero rows in
`ServiceRequest`, `Outbox`, `EstimateOutbox`, `ShopOutbox`, and `ShopOutreach`.

Additional tests cover wrong tags/account roles, private-file permissions and
symlinks, parallel-run locking, untrusted Auth origins, forbidden send routes,
uncertain mutations without retry or error-body persistence, wrong sign-in
identity, wrong deployed SHA before login, and oversized/encoded responses.
`py_compile`, scoped Ruff, and `git diff --check` also passed.

This is local API and script evidence. It does not prove a live release, worker
revision, actual Google/OSM availability, provider framing/OCR, camera hardware,
or mobile/WebView behavior. A live result retains the returned directory
availability separately: a passing participating-shop fallback with
`stale`/`unavailable` public data does not claim that live public discovery worked.
The release owner covers successful guided upload/provider UI separately.
