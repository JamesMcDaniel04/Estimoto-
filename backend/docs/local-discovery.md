# Local customer shop discovery

The authenticated `GET /v1/discovery` endpoint combines explicitly published
Estimoto providers with public OpenStreetMap listings and reviewed official business profiles. `DISCOVERY_ENABLED` controls the bootstrap `live_discovery` capability;
the default is disabled. Run `alembic upgrade head` before deploying the feature;
current head is `b7f2c9d4e1a0`. No Maps credentials are needed. This describes
current source behavior; [release status](../../docs/release-status.md) records
which revision and catalog have actually been deployed.

## API and identity

Query fields: `postal_code` (five-digit US ZIP, or saved profile ZIP),
`radius_miles=30` (the only permitted radius), optional owned `vehicle_id`,
optional `specialty` (`pdr`, `collision`, `maintenance`, `mechanical`) and
`mobile_only`, `q` (up to 120 characters) and `make_only`. Text and make filters run before the result cap. Matching uses the selected owned vehicle dynamically. Customer ownership is checked before directory I/O.

The envelope has `postal_code`, `radius_miles`, `distance_basis:zip_centroid`,
`status:ready|stale|unavailable`, `exhaustive:false`, `truncated`, `checked_at`,
`source_attributions`, `providers`, `shop_visit_alternatives`, and `message`.
A completed search adds `result_limit:30` and `selection:public_and_reviewed_businesses`;
early unavailable responses may omit those selection fields. At most **30 total**
listings are returned across the two arrays after filtering, ranking and dedupe.
Distances are approximate straight-line miles from the ZIP center, not travel
distance or a claim that mobile service reaches the ZIP.

Each listing preserves display fields and adds `source`, `source_id`,
`source_url`, `distance_miles`, `mobile_status`, `specialty_evidence`,
`vehicle_match`, `request_modes`, `favorite`, `favorite_references`, and public
contact fields where available. `media` is nullable or
`{url,kind:"logo"|"photo",attribution,source_url,background?}`; `background` can
be `light` or `dark`. The same nullable media and `source_id` appear on bootstrap
and `/v1/providers` participant rows. Source identities remain distinct:

| Source | Listing `id` | Favorite `source_id` | Booking |
| --- | --- | --- | --- |
| `estimoto` | Plus provider UUID | Original published provider source ID | Only declared `request_modes` |
| `openstreetmap` | `osm:node:123` (or way/relation) | `node:123` (or way/relation) | Call, website or saved contact flow; no bridge request |
| `my_shop` | Existing private MyShop ID | Existing private MyShop ID | Existing reviewed outreach flow; not a public-directory row |

External listings have `accepting_requests:false` and empty `request_modes`.
Mobile results require an explicitly mobile participating provider covering the
exact service ZIP. Nearby fixed shops appear separately as shop visits.
Estibot uses the same search: its `providers` field flattens the two listing
arrays, while `discovery` contains the rest of the envelope. Each card uses its
own `request_modes` and the original search context when reviewing a request.

## Reviewed business profiles and artwork

The versioned `estimoto_plus/shop_media/catalog.json` records business/contact
verification separately from artwork. A checked business badge requires an exact match to its reviewed
OSM source ID, name, address and map point. Other public map listings remain
visible with unverified-contact labels. Its review date must be within
90 days and cannot be in the future. A logo or matching chain name alone does not verify a shop. Moved, renamed or expired entries require renewed review.
The server does not perform runtime business-site searches to fill gaps.

Mini profiles expose official `website`, `phone`, `description`, `service_details`
and `phone_kind` where recorded. `verification` contains `status:contact_confirmed`,
`checked_at`, official `source_url`, formatted `address` and review `scope`.
This records published business location, repair services and contact details;
it does not certify workmanship or availability. Google ratings are not inferred.

`specialty_evidence` distinguishes official-website support, owner declaration
and supported map tags. An explicit official make listing or `service:vehicle:brand`
tag can establish `vehicle_match.status:listed_make`; chain branding, shop names
and AI suggestions cannot. Private/fleet/access=no, closed/disused/demolished and
unnamed map records are excluded. Partner location comes from the ZIP at the end
of its business address, never its first service coverage ZIP. Unknown locations
are excluded with a clear message.

Participating logos come from the original owner's authenticated catalog and use
the configured bridge origin's exact `/public/plus/providers/{source_id}/logo`
route. That route rechecks current public opt-in and logo status. Plus never
publishes a private stored-object URL or signed media reference.

Reviewed official logos or owner-published shop photos are stored as PNGs under
`estimoto_plus/shop_media/`. Their public route is
`/public/shop-media/{node|way|relation}/{number}/{sha256}.png`. The handler checks
the current directory row, business review, exact identity and content digest;
it serves only valid PNGs up to 512×512 and 512 KiB, with a one-day public cache
and digest ETag. These fixed catalog routes do not accept arbitrary fetch URLs.
Artwork provenance and optional dark-tile hints remain attached to the image.

A fallback OSM photo requires an explicit Commons `File:` tag and fixed-origin
Commons metadata with creator, license and raster MIME. A bounded metadata lookup
constructs the thumbnail/file-page URLs; it does not follow arbitrary mapper
image URLs. Failure leaves media null. Public-cache freshness/staleness limits
apply to this metadata. Clients show image credit/source, suppress referrers and
use a neutral fallback. An exact-location duplicate can retain source-bound
artwork while preserving the participating provider's handoff identity. Artwork
never changes request admission or proves specialty, and customer photos and
receipts never enter this public catalog.

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
`api.zippopotam.us/us/{ZIP}`, `overpass-api.de/api/interpreter` and the fallback `overpass.private.coffee/api/interpreter`. Requests contain
only a ZIP or rounded coordinates/radius, never account, vehicle or favorite
information. Redirects, arbitrary URLs, compressed responses and oversized or
malformed bodies are rejected. Public contact URLs are display/action data only;
the server does not fetch them.

Cache freshness is 24 hours, stale fallback is at most seven days, and failed
lookups back off five minutes. Database leases serialize ZIP and OSM provider
calls across API workers. A cold API lookup can take roughly 75 seconds at its
provider timeout ceilings; clients use an explicit 90-second timeout and retain
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

Historical results before the current reviewed-catalog change, on 2026-09-13: 17 discovery tests passed on PostgreSQL in
3.02 seconds; 266 full-suite tests passed with zero skips in 36.68 seconds.
The integrated worktree was based on `a0f43da`; root-owned capture hardening
continued afterward, so the final integration commit requires its own full run.

The full run includes actual source-module request/estimate producer→receiver
parsing for legacy omission, shop visits and mobile mode, a fresh disposable
PostgreSQL upgrade through the integrated capture head, an Alembic metadata
check, and ten-table RLS denial for an untrusted SQL role. Tests never use the
production database URL.

From the repository root, `backend/.venv/bin/python scripts/smoke_discovery.py`
starts a temporary uvicorn socket and verifies the combined 30-result cap, separate
mobile/visit results, owned favorites, Estibot parity, reviewed request replay,
synthetic delivery/status and customer isolation. It checks one directory fetch
and one handoff, then stops its server and removes its database.

A prior isolated read-only real ZIP lookup succeeded; its OSM follow-up returned
a non-200 response and was classified unavailable. That is not a successful live
OSM proof. Production readiness still requires verified deployment/migration,
provider availability or a fresh cache, and the customer UI/device checks. A
synthetic bridge receipt is not a real shop receipt or a message send.


## ZIP browsing and gaps in map coverage

Find Help maintains a search ZIP separately from the profile service ZIP.
Browsing and favorites work in other ZIPs. Requests require the saved
service ZIP to match, with an explicit profile-edit action. The make filter
and label follow the selected vehicle, including changes during a search.

If a map fetch fails or the shared budget is exhausted, recent indexed
shops within the search ZIP's radius may appear as partial/stale results.
No extra provider calls bypass the budget. A Maps search link offers an
external fallback without inventing directory results or ratings.

`official_shops.py` supplements map omissions with dated official profiles.
Their `official_website` identities can be saved as favorites; they have public
contact links and documented ZIP-centroid coordinates, and cannot receive
partner requests. Bluewater Performance and EuroWerkz list multiple makes on
their official sites and use the same dynamic matcher as every other shop.
The current official EuroWerkz profile supersedes its old map location.
Contact review does not establish quality, exact model support or availability.


The secondary Overpass endpoint is used only when the primary has no usable
cache/result. Both share the `gate:osm` database lock, daily request/byte budget,
response bounds and five-minute failure backoff. A fresh secondary cache serves
repeat queries directly. No endpoint accepts a customer-supplied fetch URL.
