# Google Places directory

Google Places API (New) is the primary live directory when `PLACES_ENABLED=true`.
`GOOGLE_PLACES_API_KEY` is a backend-only secret. Never put it in Flutter defines,
public runtime config, source control, URLs or release artifacts. Enabling the
flag without the key fails startup. `DISCOVERY_ENABLED` must also be true.

Use an owner-controlled Google Cloud project with billing and Places API (New)
enabled. Create a server key restricted to `places.googleapis.com`; where the
project uses IP restrictions, authorize the service's stable outbound IPs.
The key can be provided through Fly's secret input; do not paste it in chat.
The current task cannot configure the project until the owner completes the
Google Cloud account verification prompt.

`PLACES_DAILY_REQUESTS=100` is the default shared limit across API workers.
Atomic SQL reservations count search, ZIP fallback, favorite validation, failures,
and interrupted calls before I/O. The hard application ceiling is 1,000 per day;
set a matching project quota as another bound. Existing public-source budgets
remain separate. Requests stop for one minute after a provider error, then can
retry within the same daily budget. Each call has a bounded body and timeout,
never follows redirects, and requests only the fields the UI uses.

Text Search includes ZIP, selected make, service and optional search text.
Strict `car_repair` filtering and a 30-mile distance check exclude unrelated or
faraway results. Closed businesses are excluded. Results suggested for a make
are labeled as suggestions, never as verified expertise. A provider's result
matching the service query is not discarded just because that service is absent
from its business name. Generic listings remain available with the make filter off.

The ZIP source remains Zippopotam.us, with a live Google postal-code lookup if
that service fails. That lookup must return the exact US ZIP and is never cached.
Successful Google searches merge with recently cached public listings, official
profiles and participating Estimoto providers without waiting for Overpass.
Google failure or exhausted budget retains the existing public fallback and its
explicit partial/unavailable state. Search is bounded and is not exhaustive.

Google content is returned only for the current request, with private/no-store
HTTP headers. It never enters `public_directory_cache`, `PublicListing`, shop
contact copies, the learning corpus or telemetry. Dedicated shops persist only
the place ID and validate it through Place Details. Google cards and profiles
retain separate attribution, including returned third-party providers; their map
links identify the exact place. Public search terms and privacy disclosures are
included in the app's web assets and linked from About these results.

After configuring production, run `python -m scripts.check_places --expect-sha
<deployed-sha>` inside the deployed service. It checks New York, Denver, Los
Angeles, Chicago and Seattle using different makes. It consumes the normal shared
budget and writes no customer, vehicle, request or outreach records. Public
cache/counter writes are expected. This is production search-function evidence;
authenticated customer HTTP and native UI checks are distinct.

The requested name, address, phone and website fields use Text Search Enterprise
and Place Details Enterprise. At the September 14, 2026 published first paid
tier, search is $35/1,000 calls and details $20/1,000, before applicable free
monthly usage. The default cap therefore bounds application provider calls at
at most $3.50 per UTC day before free allowances; other clients using the same
project are outside this application cap.

Sources: [Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search),
[Places policies](https://developers.google.com/maps/documentation/places/web-service/policies),
[published pricing](https://developers.google.com/maps/billing-and-pricing/pricing).
