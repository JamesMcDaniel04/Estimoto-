# Customer Google Calendar

The Plus Calendar integration is separate from original shop connections and
original event ingestion. OAuth credentials remain in Nango. Availability uses
calendar list metadata and free/busy only; calendar labels are returned solely
to the authenticated customer UI. Google event titles, notes, participants,
locations and calendar labels are never supplied to the assistant or graph.

## Configuration and launch gate

The default is disabled. After independently verifying the owned Google OAuth
client, Calendar API, Nango redirect, consent audience and scopes, configure:

- `GOOGLE_CALENDAR_ENABLED=true`
- `NANGO_API_KEY`: dedicated server key; never put it in Flutter or logs.
- `NANGO_ENVIRONMENT=production`
- `NANGO_ALLOWED_KEY_FINGERPRINTS`: comma-separated full SHA-256 hex fingerprints
  of allowed server keys. Empty or mismatched fingerprints disable capability.
- `NANGO_CALENDAR_INTEGRATION_ID=estimoto-plus-google-calendar`

Use Nango provider template `google-calendar` with exactly:

```
https://www.googleapis.com/auth/calendar.calendarlist.readonly
https://www.googleapis.com/auth/calendar.events.freebusy
https://www.googleapis.com/auth/calendar.app.created
```

Google's authorized redirect is `https://api.nango.dev/oauth/callback`. Plus
uses hosted Connect and authenticated attempt reconciliation, not the original
retired native callback. Each attempt carries server-authored `customer_id`,
`app=estimoto-plus`, `attempt_id` and `environment=production` tags. Reconcile
requires one exact matching connection and verifies its metadata again.
Known incomplete granted-scope metadata is rejected; unavailable scope metadata
never bypasses provider checks. A provider 401/403 makes the current binding
require reconnection. Other provider failures remain unavailable/retryable.
Shared/testing credentials do not establish customer readiness.

## Routes

All routes below require verified customer authentication under
`/v1/calendar/google`. Sample customers cannot call Google.

- `GET /status`: configured, connected, status, generation,
  selected_calendar_ids, time_zone, sync_confirmed, attempt_id, sync_issues.
- `POST /connect`: returns attempt_id, validated HTTPS connect.nango.dev link,
  expires_at. The durable attempt precedes provider I/O; expires within 30 minutes.
- `POST /reconcile`: `{attempt_id}`, returning status. Stale, ambiguous and
  foreign attempts cannot change the binding.
- `GET /calendars`: `{calendars:[{id,summary,primary,time_zone,selected}]}`.
  At most five pages of 100; truncation and incomplete responses fail closed.
- `PUT /preferences`: `{selected_calendar_ids,time_zone,sync_confirmed}`.
  Select 1–10 accessible IDs and a valid IANA zone; changed preferences increment
  generation. Default display zone is `Etc/UTC`.
- `POST /availability`: `{time_min,time_max,duration_minutes,time_zone,
  day_start_hour,day_end_hour}`. Returns slots, checked_at, generation,
  time_zone, duration_minutes. Query zone must match saved preferences.
- `DELETE /connection`: `{disconnected:true}` after authoritative local
  invalidation; remote revocation is retried separately with backoff.
- `POST /sync/retry`: `{source_kind:"request"|"outreach",source_id}`. Returns
  `{source_kind,source_id,calendar_sync_status,calendar_sync_message}`.
  This explicitly rechecks one owned checked confirmed/scheduled appointment
  using current preferences and adopts its generation without changing the
  original confirmed instant, duration or review timezone.

Availability windows are at most 14 days, within 90 days, starting at least one
hour ahead. Duration is 30–480 minutes; weekday half-hour candidates fit the
entire duration within selected business hours, with at most 12 results.
Malformed/missing/per-calendar-error responses never mean free. The customer's
confirmed Plus bookings also block offers even when their Google calendar is
not selected. The duration is a reservation length, not an estimated repair time.

Outreach and directory requests accept optional calendar_check (false),
duration_minutes (60), calendar_generation (null); directory requests additionally
accept proposed_slots (0–3 aware timestamp strings). Checked requests freeze
selected IDs, generation, duration, calendar_time_zone and explicit sync consent.
The staff bridge receives only readable preferred_time text; structured Calendar
preferences stay private. Omitted new fields preserve legacy replay digests.
Accepted replay precedes fresh checks. Definite stale/busy admission errors are
422; directory rejections are durably tombstoned. Provider outages are 503.
Outreach rechecks at preparation, authorization, delivery admission and actual
shop confirmation. Customer row locks serialize admission with preference and
connection changes; bounded provider reads can briefly hold that lock during
request admission. Standalone list/availability reads release it and discard
results if generation changes before completion.

## Durable copies and recovery

Only explicitly checked, sync-enabled sources are scanned. The worker uses an
indexed private calendar_last_scan_at for fair bounded scanning; it does not
change customer-visible updated_at to track scans. Six attempts with backoff and
five-minute durable leases bound operation retries. It rechecks binding and
source state before writes. Source booking status remains authoritative.

A durable nonce and claim precede app-calendar creation. An ambiguous creation
is reconciled by exact nonce and owner role, never another blind creation POST.
Explicit definite provider rejection can be retried after fixing authorization.
Event payloads and UUID-hex event IDs persist before writes. The worker checks
exact event provenance and payload after a lost response or conflict. Reschedules
use the same ID; cancellations remove only the owned copy. Events contain a
minimal vehicle-service title, UTC times, private visibility, opaque availability,
no attendees, no description/contact/insurance data, and disabled default
reminders. Provider writes specify Retries: 0 and sendUpdates=none.

Sync statuses: not_enabled, pending, synced, conflict, reconnect_required,
attention_needed, removed. Messages contain no upstream response text.

Cancellation cleanup of an existing owned copy is permitted while the original
Nango binding remains connected, even after changing selected calendars, timezone,
or disabling future sync. Prior reschedule conflicts do not block that cleanup.
Disconnected or different-account bindings cannot delete the old copy. An apparent
missing event from a proxy 404/410 is not sufficient evidence of removal: the
worker revalidates connection ownership and access to the exact app calendar.
Shop confirmation performs its synchronous DB/provider admission transaction in
a worker thread after asynchronously reading the bounded form body.

If the app calendar is selected, its current event can overlap a reschedule.
We do not subtract a merged free/busy interval because that could hide another
event. The first release instead asks the customer to adjust the existing copy
or deselect the app calendar and retry. Intentional deletion is manual attention;
Google tombstoned IDs are not automatically recreated.

Reconnect retry preserves the prior calendar and event IDs. A new Nango
connection must prove owner access to the exact prior nonce-bearing calendar.
A different Google account cannot silently clone an existing or uncertain copy.
Disconnect keeps existing Google copies and invalidates future local access;
an external call already admitted under the customer lock may finish before
local disconnect commits. Calendar checks and event insertion cannot atomically
prevent changes made concurrently in another Google client.

## Verification

Run from backend:

```
.venv/bin/python -m pytest tests/test_customer_calendar.py tests/test_calendar_scheduling.py tests/test_calendar_sync.py -q
```

Set CALENDAR_TEST_POSTGRES_URL to a localhost disposable database containing
`test` in its name to run the API and worker tests in isolated PostgreSQL schemas.
Set PLUS_TEST_POSTGRES_URL for the fresh migration/RLS test. That test creates and
drops its own uniquely named local database and untrusted role, confirms RLS on
all four new private tables, denied inherited SELECT privileges, and zero visible
rows even after an explicit SELECT grant.

The migration is 6db7a239f1c8 after e21870f6a94b. Production applies migration
before the new API/worker; the permanent Android download router remains mounted.
No implementation test uses real Google accounts, real shop destinations or live
provider credentials.
