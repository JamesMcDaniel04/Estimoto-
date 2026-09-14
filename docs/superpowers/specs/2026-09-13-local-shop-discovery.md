# Customer local shop discovery

The customer requests repair shops within 30 miles of their ZIP, useful vehicle
specialty ranking, and a dedicated shop for each type of work. The current exact
service-ZIP and mobile-only filters hide nearby fixed shops, including Demolition
Dent when the customer searches from 80204. Both Find Help and Estibot must use the
same server discovery results.

## Directory and distance

`GET /v1/discovery` accepts `postal_code`, fixed `radius_miles=30`, optional owned
`vehicle_id`, optional `specialty` (pdr/collision/maintenance/mechanical), and
`mobile_only`. It returns `postal_code`, `radius_miles`, `distance_basis` set to
`zip_centroid`, `status` (ready/stale/unavailable), `exhaustive:false`, `checked_at`,
`source_attributions`, `providers`, `shop_visit_alternatives`, and customer `message`.
Distance is an approximate straight-line distance from a ZIP centroid, not driving
distance or an assertion of a shop's mobile service coverage.

The customer explicitly capped searches at 100 listings. Return at most 100 total
across `providers` and `shop_visit_alternatives`, after filtering, deduplication and
ranking. Include `truncated:true` and clear result-limit copy when more matches
exist. Raw bounded public data may contain more rows to select the best 100.

Combine opted-in Estimoto providers with OpenStreetMap automotive listings fetched
through a fixed-host bounded Overpass adapter. Resolve ZIPs through fixed-host
Zippopotam.us. Exclude unnamed/private/fleet/access=no/closed/disused/demolished
facilities. Bound requests, response bytes, query complexity, concurrency, rate
and cached entries; cache public results for a day and offer explicitly stale
results for at most seven days during outages. An upstream error cannot become
a confident empty result. Keep public directory caches apart from customer data.
Include source URLs and OpenStreetMap attribution/license; coverage is not exhaustive.

Each discovery provider preserves existing provider display fields and adds
`source` (estimoto/openstreetmap), stable `source_id`, `source_url`,
`distance_miles`, `mobile_status` (listed/unknown/not_listed),
`specialty_evidence`, `vehicle_match`, `request_modes`, and `favorite`.
External IDs use an explicit namespace and must never become bridge provider UUIDs.
External listings support call/website/save actions; `accepting_requests` is false
and `request_modes` is empty until the business actually participates.

Vehicle ranking uses an owned saved vehicle and explicit source evidence of make
support. A business-chain `brand` or `operator`, a suggestive name, and a model's
guess are not proof of vehicle expertise. Label evidence as listed/owner-declared,
not certified. Prefer the customer's dedicated shop, supported make/specialty
matches, then distance, while preserving useful general repair alternatives.

Mobile results require declared mobile coverage for the entered ZIP. If none
match, return nearby fixed shops in a separately labelled shop-visit section.
Estibot names the nearest appropriate participating shop and explains the visit
requirement; it cannot silently claim a fixed shop provides mobile service.

## Dedicated shops

`PUT /v1/discovery/favorites/{specialty}` accepts owned `vehicle_id`, `source`
(estimoto/openstreetmap/my_shop), and validated `source_id`. Set one dedicated shop
per customer, vehicle and work type using a natural unique key and customer lock.
`DELETE` of the same path with `vehicle_id` clears it; `GET /v1/discovery/favorites`
with owned `vehicle_id` lists preferences. Repeated writes are idempotent, and all
reads/writes are private and ownership-checked. Choosing a star never sends a shop
message or certifies the shop. Preserve source provenance and offer the existing
reviewed saved-shop contact flow. Do not expose preferences as public directory
facts or import external directory data into the private learning corpus.

## Booking admission

New request and estimate submission bodies optionally include
`service_mode:null|shop_visit|mobile`. Omitted legacy fields retain their exact
existing digest, persisted body and bridge payload. Explicit shop visits require
an opted-in accepting fixed shop, matching specialty and server-checked 30-mile
distance. Freeze the mode, ZIP and distance admission evidence privately. Explicit
mobile requests require declared mobile service and the existing exact service ZIP.
The original signed bridge receiver distinguishes shop visits from mobile coverage;
opt-outs, specialty restrictions, tenant boundaries and replay guards still apply.

## Verification

Test ZIP80204/nearby80221, radius edges, private and unknown listings, malformed or
failed upstream responses, cache expiry and bounded parallel requests, vehicle
ownership and specialty provenance, competing stars, cross-account isolation,
mobile fallback, same-body legacy replay and explicit mode admission. Inspect the
actual customer UI at phone width with long shop names; stale loads and account or
vehicle changes must not show or act on results from the previous selection.

Root owns original bridge and dashboard changes. The backend agent owns the Plus
discovery implementation and migration after the Calendar revision. Flutter work
follows the stable backend contract and is reviewed independently before release.
