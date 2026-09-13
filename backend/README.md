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

Run `PYTHONPATH=. .venv/bin/pytest -q` from `backend/`. The tests use isolated SQLite databases, injected identity verification and transport, plus one real-socket bridge receiver fixture. Run `DATABASE_URL=... .venv/bin/alembic check` after schema changes. The API does not create production/development tables automatically; run migrations first. `DATABASE_URL` has no default. Keep SQLite files and `PHOTO_DIR` outside source; persist and back up the photo directory with the database. Photos are served only through authenticated owner-scoped routes, with private no-store responses. Uploads accept decoded JPEG, PNG or WebP images up to 10 MB and 40 million pixels.

## Authentication and authorization

All customer routes require a Supabase bearer access token. On every request the server calls the configured fixed `SUPABASE_URL/auth/v1/user` with the publishable key and bearer token. It accepts only an authenticated, confirmed, non-anonymous identity with a server-returned ID and email. User-editable metadata never grants access or binds records. Every vehicle, request, estimate, photo, reminder and repair lookup is scoped to that ID. A Supabase outage returns 503; an invalid token returns 401. The client must not contain a service-role key. In production, configured Supabase and bridge URLs must be HTTPS. Bridge routes use a separate `X-Bridge-Key`; customer bearer tokens do not authorize them.

## Estimoto bridge contract

The existing Estimoto backend must implement a fixed HTTPS receiver at `BRIDGE_REQUEST_URL`. Configure the same secret as `BRIDGE_KEY` on both sides. The receiver must authenticate `X-Bridge-Key`, persist the request and its `Idempotency-Key`, and return HTTP 200, 201 or 202 with JSON `{"receipt_id":"durable-upstream-id"}`. Merely returning 2xx is insufficient; without a nonempty receipt, the request remains `failed` and retryable. The bridge should deduplicate by the idempotency key and return the same receipt on replay. Do not interpret request creation as provider acceptance or booking.

The outbox POST for creation uses `Idempotency-Key: <request_id>` and this shape:

```json
{"event":"created","request_id":"...","customer_id":"...","vehicle_id":"...","provider_source_id":"...","specialty":"pdr","description":"...","preferred_time":"...","contact":{"email":"...","name":"...","phone":"...","contact_preference":"email"},"vehicle":{"year":2020,"make":"Ford","model":"F-150","vin":"...","mileage":1000},"created_at":"..."}
```

The customer has explicitly submitted `share_contact=true` before this payload is queued. A delivered request cancelled by the customer produces a separate durable POST to the same URL with `Idempotency-Key: cancel:<request_id>` and `{"event":"cancelled","request_id":"...","provider_source_id":"..."}`. Cancelling before delivery suppresses the creation send. Outbox rows persist attempts, next retry time and receipt. Trigger `POST /v1/bridge/outbox/deliver` from an authenticated scheduler at a short interval; it processes 20 due rows, retries transport/non-receipt failures with bounded exponential backoff, and marks creation `delivered` only after a receipt. This is at-least-once delivery: the receiver's idempotency is required. A provider opted out before creation delivery is not sent and the request is marked `failed`.

The Estimoto side publishes only explicitly opted-in provider business data via `POST /v1/bridge/providers`. Required fields: `source_id`, `name`, `kind` (`shop` or `technician`), `specialties`, `postal_codes`; optional fields: `city`, `address`, `phone`, `mobile_service`, `accepting_requests`, `description`, `public_visible`. A `source_id` is stable and unique within this bridge. `public_visible=false` removes the provider from discovery; request creation also requires `accepting_requests=true` and a matching specialty. Postal filters are exact supported codes, not radius calculations. A request is rejected when the saved profile postal code is outside the provider's published codes. Demo providers are excluded from live customer discovery.

Provider decisions enter through `POST /v1/bridge/requests/{request_id}/events` with `event_id`, `provider_id`, `status`, `message`, and `scheduled_at` when status is `scheduled`. The event ID is replay protected. Allowed transitions are requested to accepted/declined/cancelled, accepted to scheduled/declined/cancelled, and scheduled to completed/cancelled. Terminal states cannot regress. Scheduling without an actual datetime fails. Events require a previously delivered request and matching provider.

Trusted estimate history enters through `POST /v1/bridge/estimates/snapshots` with `source_id`, explicit `customer_id` and `vehicle_id`, `discipline`, `description`, `status`, and optional `claim_number`, `date_of_loss`, `amount_cents`, `provider_name`. Trusted repair history enters through `POST /v1/bridge/repairs/snapshots` with `source_id`, explicit `customer_id` and `vehicle_id`, `provider_name`, `title`, `status`, `estimated_completion`, and `stages` (`title`, `status`, `date`). The customer and vehicle must already exist and be linked; email or VIN is never used to claim a record. Existing source IDs cannot be rebound to another customer or vehicle. Customer-created estimates remain drafts with `amount_cents=null`; submission is unavailable until a live estimator integration is implemented.

The deterministic assistant returns advice, a structured provider-search intent and provenance-labeled YouTube search links. It never creates requests, diagnoses damage, claims provider availability, returns invented quote amounts, or presents CARFAX as connected.
