# Estimoto + customer API

This is the separate customer service for the Estimoto + app. It does not provision or join a shop account. The API contract is `../docs/api-contract.md`. Production requires a dedicated private PostgreSQL database, Supabase Auth URL and publishable key, a persistent private photo volume, and the Estimoto bridge described below. The bridge receiver and production deployment are separate rollout work; this repository supplies the customer-side contract and outbox.

## Run locally

Use Python 3.13. From `backend/`:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
cp .env.example .env
# Edit .env with absolute paths and local settings; load it in your shell.
set -a; source .env; set +a
.venv/bin/alembic upgrade head
.venv/bin/uvicorn estimoto_plus.app:create_app --factory --reload
```

For a fully isolated fictional demo, set `ENVIRONMENT=development`, `DEV_SESSIONS_ENABLED=true`, and a randomly generated `DEV_TOKEN_SECRET` of at least 32 characters. `POST /v1/dev/session` seeds one fictional customer, vehicle and provider and returns a local token. It is unavailable in production even if the flag and secret are present. Demo requests stay `local_preview` and never enter the outbound bridge. Neither a failed live sign-in nor a failed bridge call triggers demo mode.

Run `PYTHONPATH=. .venv/bin/pytest -q` from `backend/`. The tests use isolated SQLite databases, injected identity verification and transport, plus one real-socket bridge receiver fixture. Run `DATABASE_URL=... .venv/bin/alembic check` after schema changes. The API does not create production/development tables automatically; run migrations first. `CORS_ORIGINS` is an explicit comma-separated browser origin allowlist (empty by default, no wildcard); native clients do not need it. `DATABASE_URL` has no default. Keep SQLite files and `PHOTO_DIR` outside source; persist and back up the photo directory with the database. Photos are served only through authenticated owner-scoped routes, with private no-store responses. Uploads accept decoded JPEG, PNG or WebP images up to 10 MB and 40 million pixels. The total photo request body is capped at 11 MiB at ASGI receive time, including streaming requests without Content-Length; authentication and owner checks precede multipart parsing.

## Authentication and authorization

Private garage uploads and representative CarsXE imagery use the [vehicle-image contract](docs/vehicle-images.md). Run migration `e21870f6a94b` before deploying the image routes and configure `CARSXE_API_KEY` only on the server.

All customer routes require a Supabase bearer access token. On every request the server calls the configured fixed `SUPABASE_URL/auth/v1/user` with the publishable key and bearer token. It accepts only an authenticated, confirmed, non-anonymous identity with a server-returned ID and email. User-editable metadata never grants access or binds records. Every vehicle, request, estimate, photo, reminder and repair lookup is scoped to that ID. A Supabase outage, rate limit, or malformed upstream response returns 503; invalid credentials return 401. The client must not contain a service-role key. In production, configured Supabase and bridge URLs must be HTTPS. Bridge routes use a separate `X-Bridge-Key`; customer bearer tokens do not authorize them.

## Estimoto bridge contract

The existing Estimoto backend must implement a fixed HTTPS receiver at `BRIDGE_REQUEST_URL`. Configure the same secret as `BRIDGE_KEY` on both sides. The receiver must authenticate `X-Bridge-Key`, persist the request and its `Idempotency-Key`, and return HTTP 200, 201 or 202 with JSON `{"receipt_id":"durable-upstream-id"}` (a nonblank string of at most 200 characters in a response body of at most 4 KiB). Merely returning 2xx is insufficient; without a nonempty receipt, the request remains `failed` and retryable. The bridge should deduplicate by the idempotency key and return the same receipt on replay. Do not interpret request creation as provider acceptance or booking.

The outbox POST for creation uses `Idempotency-Key: <request_id>` and this shape:

```json
{"event":"created","request_id":"...","customer_id":"...","vehicle_id":"...","provider_source_id":"...","service_postal_code":"80202","specialty":"pdr","description":"...","preferred_time":"...","contact":{"email":"...","name":"...","phone":"...","contact_preference":"email"},"vehicle":{"year":2020,"make":"Ford","model":"F-150","vin":"...","mileage":1000},"created_at":"..."}
```

The customer has explicitly submitted `share_contact=true` before this payload is queued. A customer cancellation after any creation attempt has started produces a separate durable POST to the same URL with `Idempotency-Key: cancel:<request_id>` and `{"event":"cancelled","request_id":"...","provider_source_id":"..."}`. This includes attempts that timed out without a local receipt. The receiver **must persist a cancellation tombstone even if it has not yet seen creation**, reject or neutralize a later creation for that request ID, and propagate cancellation if it already forwarded the request to a provider. A cancellation before any attempt suppresses creation without a tombstone. The customer API does not retry creation after cancellation. Outbox rows persist the immutable reviewed payload and hash, attempt count, claim token, 60-second lease, next retry time, suppression and receipt. Trigger `POST /v1/bridge/outbox/deliver` from an authenticated scheduler at a short interval; it processes up to 20 due rows, retries transport/non-receipt failures with bounded exponential backoff, and marks creation `delivered` only after a receipt. Claims and finalization are conditional database writes; network I/O is outside transactions. This is at-least-once delivery: the receiver's idempotency and tombstone semantics are required. A provider opted out before a creation claim is not sent and its outbox row is suppressed with a failed delivery status. Cancellation tombstones remain deliverable after opt-out.

The Estimoto side publishes only explicitly opted-in provider business data via `POST /v1/bridge/providers`. Required fields: `source_id`, `name`, `kind` (`shop` or `technician`), `specialties`, `postal_codes`; optional fields: `city`, `address`, `phone`, `mobile_service`, `accepting_requests`, `description`, `public_visible`. A `source_id` is stable and unique within this bridge. `public_visible=false` removes the provider from discovery; request creation also requires `accepting_requests=true` and a matching specialty. Postal filters are exact supported five-digit US ZIP codes, not radius calculations. ZIP+4 input is normalized to its five-digit service area. A request requires a saved valid ZIP and is rejected when it is outside the provider's published codes. The validated ZIP is frozen in the outbound snapshot; profile or vehicle edits do not change retry payloads. Demo providers are excluded from live customer discovery.

Provider decisions enter through `POST /v1/bridge/requests/{request_id}/events` with `event_id`, `provider_id`, `status`, `message`, and `scheduled_at` when status is `scheduled`. The event ID is replay protected. Allowed transitions are requested to accepted/declined/cancelled, accepted to scheduled/declined/cancelled, and scheduled to completed/cancelled. Terminal states cannot regress. Scheduling without an actual datetime fails. Events require a previously delivered request and matching provider.

Trusted estimate history enters through `POST /v1/bridge/estimates/snapshots` with `source_id`, explicit `customer_id` and `vehicle_id`, `discipline`, `description`, `status`, and optional `claim_number`, `date_of_loss`, `amount_cents`, `provider_name`. Trusted repair history enters through `POST /v1/bridge/repairs/snapshots` with `source_id`, explicit `customer_id` and `vehicle_id`, `provider_name`, `title`, `status`, `estimated_completion`, and `stages` (`title`, `status`, `date`). The customer and vehicle must already exist and be linked; email or VIN is never used to claim a record. Existing source IDs cannot be rebound to another customer or vehicle. Customer-created estimates remain drafts with `amount_cents=null`; submission is unavailable until a live estimator integration is implemented.

The deterministic assistant returns advice, a structured provider-search intent and provenance-labeled YouTube search links. It never creates requests, diagnoses damage, claims provider availability, returns invented quote amounts, or presents CARFAX as connected.
