# Private garage vehicle images

All three routes use the normal confirmed customer Bearer token and check the saved vehicle's customer ID. Foreign or deleted vehicles return 404; unsigned requests return 401. Image bytes and metadata are private with `Cache-Control: private, no-store` and `X-Content-Type-Options: nosniff`. There is no public upload URL, customer-controlled fetch URL, or bridge photo access to these images. Garage photos are separate from estimate evidence and never become required capture photos or get sent to a shop.

## Client contract

`GET /v1/vehicles/{vehicle_id}/image` returns:

- 200 `image/webp` bytes, `X-Vehicle-Image-Source: upload|carsxe`, and a quoted SHA-256 `ETag`.
- 204 with `Retry-After` seconds if stock is unavailable, a lookup is already running, or provider backoff applies. Do not retry during widget renders. Retain the neutral “Add your photo” state until an explicit reload or the retry window.
- 429 if the customer has exhausted distinct paid lookup reservations this hour.
- 503 if an existing private upload is unavailable or fails its saved digest; do not silently replace the customer's image with stock.

`POST /v1/vehicles/{vehicle_id}/image` accepts multipart with exactly one `file` part. The decoded content must be a static JPEG, PNG, or WebP, at most 10 MiB, 40 million pixels, and 16,384 pixels on either side. MIME headers and filenames do not establish the image format. The server applies EXIF orientation, discards EXIF/XMP/ICC/text metadata, scales within 1600×1200, and saves a WebP of at most 1 MiB. Success is 200:

```json
{"source":"upload","image_version":"<sha256-of-stored-WebP>"}
```

Vehicle objects in bootstrap/create/update add nullable `image_version`. A nonnull value means a saved upload; clients can invalidate their in-memory image with it. Keep vehicle year/make/model in the stock cache identity on the client too. Identical upload retries reuse the saved file and do not spend the durable upload quota; they still count toward the attempt limit. Uploads immediately take priority over stock, including a stock request that was already running.

`DELETE /v1/vehicles/{vehicle_id}/image` returns 204 and removes the upload. The next GET falls back to stock. Repeated deletion is safe. Successful vehicle deletion removes its owned upload too. The service currently has no customer account-deletion API; an administrative account purge must remove the customer's referenced private files along with its records.

Use “Your photo” for `upload` and “Representative image” for `carsxe`. Stock is never proof of this exact vehicle, trim, color, damage condition, or ownership. CORS exposes the source, ETag and Retry-After headers for explicitly allowed preview origins.

## Provider and storage behavior

Configure `CARSXE_API_KEY` as a server secret, reused privately from the original Estimoto CarsXE account. Plus reuses the fixed `https://api.carsxe.com/images` API and response shape; it does not reuse the original URL-only cache, which cannot enforce Plus byte security or paid-request concurrency. Only the saved year/make/model leave Plus. No VIN, customer identity, or uploaded bytes go to CarsXE. Provider URL credentials, responses and exceptions are never logged.

Requests use `validate=true`, `size=Medium`, and `license=ModifyCommercially`, as documented by [CarsXE](https://docs.carsxe.com/api-reference/images/vehicle-images). The provider can return comparison-page images and wrong generations even with validation enabled. Plus additionally requires make, model and the requested year in the decoded image URL path. Opaque URLs and comparison-page captions alone fail this conservative check. At most ten metadata candidates are examined and three qualifying image downloads attempted. This relevance check does not identify the customer's particular vehicle.

Image downloads require HTTPS/443 with no URL credentials. Every destination and redirect resolves solely to public IPs; the selected address is pinned to the socket while TLS verifies the original hostname. Private, loopback, link-local and alternate IPv4-in-IPv6 routing forms are rejected. Requests ignore environment proxies, forward no authentication to image hosts, allow at most three redirects, cap decoded response bytes, and apply an overall download deadline. Downloaded bytes pass the same raster validation/transcoding as uploads.

The global stock cache uses a SHA-256 identity of normalized full year/make/model fields. A database lease is committed before provider I/O; concurrent requests share the reservation and a crashed attempt can recover after 120 seconds. Successful stock bytes cache for 365 days; missing or failed identities cache for one day. Provider auth/credit/429 errors block new distinct lookups for one hour, transport/5xx failures for five minutes. Stock reservations are capped at ten per customer per hour and 200 globally per UTC day. Cache hits do not consume quota. Cache retention is capped at 2,000 entries and 100 MiB, with inactive oldest entries evicted under the provider lock.

Uploads reserve at most 40 decode attempts/customer/hour, persist at most 20 changed images/hour, and use at most 20 MiB/customer. A process permits at most two concurrent raster decodes. Request bodies are capped at 11 MiB before multipart spooling, including chunked requests. Upload files use private UUID names with mode 0600 under `PHOTO_DIR/vehicle-images`; superseded and deleted references are removed after database commit. An uncertain commit keeps its file so an acknowledged database write cannot point at a deleted image; the digest makes retry converge. Operational orphan cleanup must check database references before deleting any objects.

Migration `e21870f6a94b` adds nullable upload fields, the stock byte cache, and provider quota/backoff state. New tables enable PostgreSQL RLS and revoke direct anonymous/authenticated/public access. Deploy the migration before the application; `/ready` requires this revision. No CarsXE key is required to accept customer uploads.

## Verification

Focused tests use synthetic rasters and injected provider functions on SQLite and optional isolated PostgreSQL schemas. They cover customer isolation, EXIF removal and orientation, content/byte/pixel/animation limits, replay, file replacement/deletion, stock/upload races, persistent quotas/leases, cache bounds, provider backoff, changed vehicle identity, public-address validation, redirect rebinding, provider-key suppression, and wrong-model/year rejection.

```sh
PLUS_TEST_POSTGRES_URL='postgresql+psycopg://plus_test@127.0.0.1:55439/estimoto_scope_test_plus?client_encoding=utf8' \
  .venv/bin/python -m pytest -q tests/test_vehicle_images.py
```

Two visually inspected representative demo assets were selected from CarsXE results on 2026-09-13 using the commercial modification filter. The 2021 Tacoma came from a `2021-Toyota-Tacoma` source on `static.tcimg.net`; the 2022 Q5 came from a `2022-Audi-Q5` source on `file.kelleybluebookimages.com`. Earlier wrong-generation and wrong-make candidates were rejected. These source checks and visual inspections are distinct from live customer upload/device verification.
