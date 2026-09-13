# Estimoto + Google Calendar design

The customer connects Google once, chooses calendars that affect availability,
and can ask Estibot for repair times around those commitments. Calendar access
belongs to the authenticated Plus customer and never to an Estimoto shop.

## Product flow

Garage and Estibot expose a Calendar page. Connect opens Nango's hosted Google
consent flow in the system browser. Returning to the app reconciles the current
customer's server-created attempt. The customer selects 1–10 calendars, an IANA
time zone, and whether to copy confirmed appointments to an Estimoto + calendar.
No existing event is changed. Calendar names appear only in this private UI.

In My shops outreach, Find available times returns up to twelve candidates for
a chosen date range, appointment duration, and local business hours. The
customer chooses 1–3 times, reviews the existing exact email/contact share, and
authorizes it. Both draft preparation and authorization recheck availability.
The shop must confirm an offered time; confirmation rechecks checked requests.
Calendar outages, lost access, or a newly busy slot require new choices rather
than claiming an appointment was booked. The duration is a customer-selected
reservation length, not a repair-time estimate.

The directory-provider request composer can use the same available-time picker.
It submits structured proposed_slots/duration_minutes/calendar_check alongside
preferred_time. The backend verifies those times and freezes them in the request;
the existing staff bridge receives a readable preferred_time string, so original
Estimoto requires no bridge schema change. A scheduled provider response remains
the authority for the actual appointment. If it conflicts with the customer's
calendar, Plus surfaces attention-needed instead of silently moving the booking.

When a checked My shops request is confirmed or a directory request is scheduled,
a durable worker creates or updates one private event in the app-created calendar
if the customer enabled sync. Cancellations remove only the corresponding app
event; reschedules update the same ID. Existing unconnected requests do not cause
historical bulk imports when someone connects. If a newly confirmed time is busy,
the source booking remains visible with a calendar conflict status. Disconnect
immediately invalidates attempts, pending reads/writes and automatic sync, and
removes the dedicated Nango connection; existing Google copies remain visible.

## Binding constraints

- Integration ID: `estimoto-plus-google-calendar`; provider template: `google-calendar`.
- Scopes: `https://www.googleapis.com/auth/calendar.calendarlist.readonly`, `https://www.googleapis.com/auth/calendar.events.freebusy`, `https://www.googleapis.com/auth/calendar.app.created`.
- Do not import Google event titles, descriptions, attendees or locations into Estibot, GraphRAG, shop data or analytics.
- No Google tokens in client code, local client storage, logs or Plus response bodies.
- Google consent and a verified production OAuth client are required before enabling live connections.
- No attendees, conferencing, default reminders, or notification sends in app-created events.
- All private endpoints require the existing verified customer Auth dependency and ownership checks.
- Missing, malformed, truncated or per-calendar-error free/busy responses fail closed.
- Start times are offset-aware UTC instants; display and business hours use a validated IANA time zone.
- Duration: 30–480 minutes, default 60; queries cover at most 14 days within the next 90 days; starts at least one hour ahead.
- Availability checks allow at most 10 selected calendars and return at most 12 candidate slots.
- Preserve existing idempotency and immutable review behavior for requests made by builds 1–5.
- Sample mode cannot open OAuth, contact a provider or write a real calendar.

## API contract

Base `/v1/calendar/google`:

- `GET /status` → `{configured, connected, status, generation, selected_calendar_ids, time_zone, sync_confirmed, attempt_id, sync_issues}`. Status values: unavailable/disconnected/connecting/connected/reconnect_required. IDs in this private response are customer-owned; attempt_id may be null.
- `POST /connect` → `{attempt_id, connect_link, expires_at}`. Store a server-generated attempt and expiry before external calls. Limit abuse using customer rate buckets. A fresh attempt invalidates the previous attempt; return only a validated HTTPS connect.nango.dev link.
- `POST /reconcile` body `{attempt_id}` → status response. Require current unexpired attempt plus Nango integration/environment/customer/attempt ownership tags; reject ambiguous or unrelated connections.
- `GET /calendars` → `{calendars:[{id, summary, primary, time_zone, selected}]}`. Bounded pagination; partial list must not be reported as complete.
- `PUT /preferences` body `{selected_calendar_ids, time_zone, sync_confirmed}` → status response. Validate IDs against the customer's accessible calendars; bump generation on changed scheduling preferences. No app-calendar creation until explicitly enabling sync.
- `POST /availability` body `{time_min,time_max,duration_minutes,time_zone,day_start_hour,day_end_hour}` → `{slots:[{start,end}],checked_at,generation,time_zone,duration_minutes}`. Hours default 9 and 17, weekdays by default; reject invalid windows. All selected calendars must succeed.
- `DELETE /connection` → `{disconnected:true}`. Local invalidation is committed even if revocation needs retry. Never silently leave the app connected after a provider outage.

Extend outreach and directory request create bodies with optional
`calendar_check` (default false), `duration_minutes` (default 60),
`calendar_generation` (nullable), and (directory only) `proposed_slots` (0–3).
Old-client omitted fields must not alter existing payload hashes on replay.
Definitive calendar conflicts/stale generations use HTTP 422 after checking for
already-accepted same-key replay. Directory rejection outcomes are persisted;
provider outages remain 503 and must not clear uncertain operations.
The server freezes `calendar_time_zone` from connection preferences and exposes
it in source views. Availability time_zone must match those saved preferences.
Use `Etc/UTC` as the default zone. Flutter uses pinned `timezone: 0.11.1` with
embedded IANA data; add a shared formatting helper, never infer zone from an abbreviation.
Server snapshots retain verified generation, selected IDs and duration; changing
preferences or disconnecting invalidates pending checked authorizations.
Outreach views expose these fields plus `calendar_sync_status` and
`calendar_sync_message`. Directory request views expose the same status fields.

## Persistence and provider adapter

New private SQLAlchemy tables and a forward Alembic migration store connection,
attempt, calendar provision claim and appointment synchronization operations.
Enable RLS and revoke anon/authenticated access like the existing private tables.
Use customer-row locking consistently before changing connection or scheduling
state, and recheck the same generation before persisting provider responses.

Use fixed `https://api.nango.dev` endpoints, server-owned provider and connection
headers, bounded httpx timeouts, response limits, and explicit `Retries: 0` for
writes. Store only metadata necessary to connect and schedule. Nango owns tokens.
Tag Connect sessions with customer_id, Plus app marker, attempt_id and environment;
never accept a client-provided connection ID or raw Google URL.

App calendar creation has no Google client idempotency ID. Persist a nonce and
durable claim before POST; reconcile uncertain results from the accessible app
calendar list by exact nonce/provenance and owner role. Never blindly repeat
calendar creation after an ambiguous result. Mark attention-needed if no safe
reconciliation is possible. App event IDs are deterministic base32hex UUID hex.
Persist the exact payload and operation ID before writes. Resolve timeout/409 by
GET at that exact ID and verify private provenance; never overwrite an unrelated
event. A durable lease prevents concurrent worker writes. Recheck generation on
every operation, including retries and disconnect. No automatic unlimited retry.

## Verification and launch gates

Tests cover auth isolation, attempt spoof/replay/late-return, reconnect/revoke,
partial scopes, calendar pagination/errors, all-day busy intervals, overlap/DST,
duration and window limits, stale generation, provider outages, send-time
conflict, old request replay, uncertain calendar creation, exact-event recovery,
concurrent workers, reschedules/cancellations, and absence of raw calendar text
from assistant/history paths. Flutter tests cover return from browser, calendar
selection, time suggestions/review, pending retry and account switch.

Provider setup is a separate gate: verify Calendar API enabled, owned OAuth
client, Nango callback, exact requested scopes and consent audience. Public
customer readiness must not be inferred from Google's shared/testing credentials
or a seven-day testing refresh token. A real Google connection requires the
customer to complete consent. No real shop outreach is sent by implementation QA.

Sources: https://developers.google.com/workspace/calendar/api/auth ;
https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query ;
https://developers.google.com/workspace/calendar/api/v3/reference/events/insert ;
https://nango.dev/docs/reference/backend/http-api/connect/sessions/create .
