# Local customer shop discovery

The authenticated `GET /v1/discovery` endpoint combines explicitly published
Estimoto providers with a bounded public OpenStreetMap index. Set
`DISCOVERY_ENABLED=true` only after deploying migration `e96b17c4d502` and its
current descendants. The default is disabled. No Maps credentials are needed.
The bootstrap capability is `live_discovery`.

## API and identity

Query fields: `postal_code` (five-digit US ZIP, or saved profile ZIP),
`radius_miles=30` (the only permitted radius), optional owned `vehicle_id`,
optional `specialty` (`pdr`, `collision`, `maintenance`, `mechanical`) and
`mobile_only`. Customer ownership is checked before directory I/O.

The envelope has `postal_code`, `radius_miles`, `distance_basis:zip_centroid`,
`status:ready|stale|unavailable`, `exhaustive:false`, `truncated`, `checked_at`,
`source_attributions`, `providers`, `shop_visit_alternatives`, and `message`.
At most **100 total** listings are returned after filtering, ranking and dedupe.
Distances are approximate straight-line miles from the ZIP center, not travel
distance or a claim that mobile service reaches the ZIP.

Each listing preserves provider display fields and adds `source`, `source_id`,
`source_url`, `distance_miles`, `mobile_status`, `specialty_evidence`,
`vehicle_match`, `request_modes`, `favorite`, and optional public `website` and
`email`. Source identities are intentionally distinct:

| Source | Listing `id` | Favorite `source_id` | Booking |
| --- | --- | --- | --- |
| `estimoto` | Plus provider UUID | Original published provider source ID | Only declared `request_modes` |
| `openstreetmap` | `osm:node:123` (or way/relation) | `node:123` (or way/relation) | Call, website or saved contact flow; no bridge request |
| `my_shop` | Existing private MyShop ID | Existing private MyShop ID | Existing reviewed outreach flow |

External listings have `accepting_requests:false` and empty `request_modes`.
Mobile results require an explicitly mobile participating provider that covers
the exact service ZIP. Nearby fixed shops appear separately as shop visits.
Estibot calls the same search: its `providers` field flattens the two listing
arrays, while `discovery` contains the rest of the envelope. Each card must use
its own `request_modes` and the original search context when reviewing a request.

`specialty_evidence` is owner-declared or an explicit OSM tag, never certification.
Only `service:vehicle:brand` can establish `vehicle_match.status:listed_make`.
Chain `brand`, `operator`, a shop name and AI suggestions cannot establish make
expertise. A general `shop=car_repair` tag establishes only a general mechanical
listing. Private/fleet/access=no, closed/disused/demolished and unnamed records
are excluded. Published partner location comes from a ZIP at the end of its
business address, never its first service coverage ZIP. Unknown locations are
excluded with a clear message.

## Private dedicated shops

`GET /v1/discovery/favorites?vehicle_id=...` returns a bare array of
`{vehicle_id,specialty,source,source_id}`. `PUT /v1/discovery/favorites/{specialty}`
accepts `{vehicle_id,source,source_id}` and returns the saved reference. `DELETE`
of the same path with `vehicle_id` returns `{removed:true}`.

The key is customer + owned vehicle + work type. Writes take the customer lock;
repeating a write is idempotent. An OSM favorite must reference the recent public
index, a participating favorite must still be public, and a MyShop must belong
to the caller. A star neither sends a message nor certifies a shop. Favorites
are stored apart from the public cache and the private learning corpus. The
vehicle foreign key cascades preference deletion.

The existing MyShop API supplies its private display details. Estibot can name
an owned dedicated MyShop and return `intent:shop_outreach` plus
`dedicated_shop_id`; it directs the customer to the existing review flow and
creates no outreach or outbox item.

## Reviewed request and estimate handoff

New request and estimate submit bodies optionally accept
`service_mode:null|shop_visit|mobile`. **Omitting this field retains the legacy
request hash and bridge payload.** Explicit mobile mode requires declared mobile
service plus the exact service ZIP. Shop visits require an accepting opted-in
shop with the requested specialty and a fresh server-checked distance <=30 miles.
The private row freezes mode, ZIP coordinates, distance basis and the published
address hash. Only `service_mode` is added to the bridge payload; private distance
proof is not exported. Workers validate the frozen proof, source identity,
opt-in/acceptance/specialty and published address before first delivery. Profile
changes cannot reinterpret a previously reviewed request.

The original bridge receiver must support the optional mode contract before
clients expose this option. Omitted legacy bodies still use exact ZIP coverage.
No public OSM ID can become a participating bridge target. Definite mode/location
rejections return 422 and service request outcomes are durably remembered;
provider/geocoding outages remain 503. Accepted same-key replays precede geography
checks and do not need the provider to be online.

## Provider limits and availability

Outbound directory URLs are fixed HTTPS hosts:
`api.zippopotam.us/us/{ZIP}` and `overpass-api.de/api/interpreter`. Requests contain
only a ZIP or rounded coordinates/radius, never account, vehicle or favorite
information. Redirects, arbitrary URLs, compressed responses and oversized or
malformed bodies are rejected. Public contact URLs are display/action data only;
the server does not fetch them.

Cache freshness is 24 hours, stale fallback is at most seven days, and failed
lookups back off five minutes. Database leases serialize ZIP and OSM provider
calls across API workers. A cold API lookup can take roughly 50 seconds at its
provider timeout ceilings; clients use an explicit 60-second timeout and retain
account/vehicle guards. Cache hits do not contact a provider. Each search can
resolve at most four cold partner ZIPs and scans at most 500 partners; its public
cache is capped at 128 records and its normalized OSM index at 20,000 records.
Search calls are limited to 120 per customer per hour.

The durable UTC-day `public_directory_budgets` row enforces these OSM settings:

| Setting | Default | Hard ceiling |
| --- | --- | --- |
| `DISCOVERY_DAILY_REQUESTS` | 30 attempts/day | 100 |
| `DISCOVERY_DAILY_BYTES` | 8 MiB/day | 10,000,000 bytes |

A request reserves at most 3 MiB of remaining allowance before I/O. Actual
consumed body bytes, including errors, are charged and unused reservation is
refunded. A process crash keeps its reservation charged. Counts are global to all
customers/ZIPs/workers. Exhaustion returns stale/unavailable without another OSM
call; no alternate mirror bypasses the budget. Raw responses accept at most
10,000 elements and each normalized listing stays within the 30-mile radius.

The response includes [OpenStreetMap attribution and ODbL license](https://www.openstreetmap.org/copyright)
and the Zippopotam.us source attribution. Public search is not exhaustive and
must never be labelled "all shops" or a verified specialty directory.

## Verification and remaining operational proof

All automated fixtures are synthetic; no real customer, calendar, shop request,
message or public provider call is used in the following checks. Run from
`backend/`:

```sh
DISCOVERY_TEST_POSTGRES_URL='postgresql+psycopg://plus_test@127.0.0.1:55439/estimoto_scope_test_plus?client_encoding=utf8' .venv/bin/python -m pytest tests/test_discovery.py -q
PLUS_TEST_POSTGRES_URL='postgresql+psycopg://plus_test@127.0.0.1:55439/estimoto_scope_test_plus?client_encoding=utf8' ESTIMOTO_BRIDGE_BACKEND='/Users/jamesmcdaniel/Estimoto/.worktrees/plus-launch-integration-20260913/backend' ESTIMOTO_BRIDGE_PYTHON='/Users/jamesmcdaniel/Estimoto/backend/.venv/bin/python' .venv/bin/python -m pytest -q
```

Candidate results on 2026-09-13: 17 discovery tests passed on PostgreSQL in
3.02 seconds; 266 full-suite tests passed with zero skips in 36.68 seconds.
The integrated worktree was based on `a0f43da`; root-owned capture hardening
continued afterward, so the final integration commit requires its own full run.

The full run includes actual source-module request/estimate producer→receiver
parsing for legacy omission, shop visits and mobile mode, a fresh disposable
PostgreSQL upgrade through the integrated capture head, an Alembic metadata
check, and ten-table RLS denial for an untrusted SQL role. Tests never use the
production database URL.

From the repository root, `backend/.venv/bin/python scripts/smoke_discovery.py`
starts a temporary uvicorn socket and verifies the combined100 cap, separate
mobile/visit results, owned favorites, Estibot parity, reviewed request replay,
synthetic delivery/status and customer isolation. It checks one directory fetch
and one handoff, then stops its server and removes its database.

A prior isolated read-only real ZIP lookup succeeded; its OSM follow-up returned
a non-200 response and was classified unavailable. That is not a successful live
OSM proof. Production readiness still requires verified deployment/migration,
provider availability or a fresh cache, and the customer UI/device checks. A
synthetic bridge receipt is not a real shop receipt or a message send.
