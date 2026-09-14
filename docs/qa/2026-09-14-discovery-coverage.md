# Find Help coverage and dynamic vehicle matching — September 14, 2026

Application source deployed: `1e199ac022a052e1d4e3dce8e75c0ceeb95a122e`.

## What was wrong

Public search admitted only a small manually reviewed catalog despite 809
public shops in the live index. Search ZIP changes required editing the saved
profile. Participating providers ranked ahead of documented vehicle-make
matches. Bluewater was missing from both the map index and reviewed catalog.
Cold searches also depended on a single public map endpoint; a New York ZIP
resolved correctly but its shop lookup failed.

## Delivered

- Search a ZIP without changing the profile; search shop names or services
  before applying the 30-result cap.
- Rank documented support for the selected vehicle's make dynamically. The
  make filter label follows the car, and edits to the same vehicle trigger a
  fresh search. Unknown support remains unverified; general repair is still
  available when the make-only filter is off.
- Show public map listings with clear unverified-contact labels. Exact current
  official reviews continue to receive checked-contact badges.
- Add Bluewater Performance and EuroWerkz official profiles, including their
  published supported makes and contact details. Suppress EuroWerkz's old map
  location while its current official profile is active. These businesses can
  be saved as favorites/contacts; they are not marked as participating partners.
- Reuse recent nearby indexed shops after a failed new-ZIP fetch. Add one fixed
  secondary public endpoint with shared request/byte limits and failure backoff.
- Use a provider bounding-box query followed by the unchanged 30-mile distance
  filter. Provide an explicit Google Maps search link when coverage is missing.
- Keep request geography tied to the saved service ZIP, with a visible action
  to update it when browsing elsewhere.

## Evidence

- Full backend suite against SQLite and local PostgreSQL: 443 passed, seven
  optional original-backend contract checks skipped; one dependency warning.
- Full Flutter suite: 248 passed. Final discovery tests and analyzer passed
  after the timeout/copy adjustment. Capture web: 19 tests passed.
- The local HTTP discovery smoke passed, including ownership, favorites,
  request replay, synthetic delivery and the shared budget.
- Deployed browser: alternate-ZIP controls appear; changing Audi Q5 to Toyota
  Tacoma changes the make filter to Toyota and preserves the search ZIP.
- Production search function with a synthetic, non-persisted customer/vehicle
  context and real public data: ZIP 80229 + Audi + Bluewater returns Bluewater
  with documented Audi support. ZIP 80204 + Toyota ranks The Toy Shop first.
  This is not a signed-in customer HTTP or physical-device test.
- Deploy script exited 0. `/version` matched the source above; `/ready` passed
  at schema `b7f2c9d4e1a0`. Served JavaScript matched the local artifact:
  `de7c6e6a24ada01250e3b596d6300a9fd67cd339104fbf3e6ed0aaaad638def2`.

## Remaining coverage and distribution limits

**Nationwide reliability is not closed.** The live ZIP 10001 search still
returned `unavailable` with zero shops after primary/secondary public-provider
attempts and the query improvement. No reset bypassed provider backoff or the
shared budget. The public source remains incomplete and intermittently
unavailable; the Maps link is an external fallback, not in-app directory proof.
No Google Places/business-directory credential is configured in Plus. A
business-directory integration and its project configuration are the remaining
follow-up for broader coverage; no paid provider has been activated.

Backend changes apply to existing native clients. New ZIP/name/filter controls
are deployed on web; native builds have not been republished because their
release-signing setup remains unavailable in the active checkouts.

## Business and provider sources

- [Bluewater official business/contact information](https://bwperformance.com/about-us/)
- [Bluewater's published Audi services](https://bwperformance.com/audi-service-repair-denver/)
- [EuroWerkz official address and supported vehicles](https://www.eurowerkzmotorsport.com/)
- [Public Overpass instances](https://wiki.openstreetmap.org/wiki/Overpass_API)
- [Overpass bounding boxes](https://dev.overpass-api.de/overpass-doc/en/full_data/bbox.html)
- [Google Places text search](https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places/searchText)
