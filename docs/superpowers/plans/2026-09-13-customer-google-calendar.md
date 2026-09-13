# Customer Google Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Plus customers connect Google Calendar, choose conflict-free repair offers through Estibot, and synchronize confirmed appointments.

**Architecture:** Dedicated customer-owned Nango connections expose calendar selection and free/busy only. Existing immutable request review and shop confirmation remain the scheduling authority; a separate durable worker synchronizes app-owned Google events.

**Tech Stack:** Existing Python 3.13 FastAPI, SQLAlchemy, Alembic, httpx and PostgreSQL backend; Flutter/Dart with url_launcher, current repositories and customer workspace guards.

**Spec:** `docs/superpowers/specs/2026-09-13-customer-google-calendar.md`

## Global Constraints

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

---

### Task 1: Customer Calendar backend and scheduling contract

**Files:**
- Create: `backend/estimoto_plus/calendar_models.py`, `calendar_provider.py`, `calendar_routes.py`, `calendar_scheduling.py`, `calendar_sync.py`.
- Create: `backend/alembic/versions/` forward revision after `e21870f6a94b`.
- Modify: `backend/estimoto_plus/app.py`, `config.py`, `schemas.py`, `customer_routes.py`, `saved_shops.py`, `shop_models.py`, `models.py`, `assistant_model.py`.
- Test: `backend/tests/test_customer_calendar.py`, `test_calendar_scheduling.py`, `test_calendar_sync.py`.
- Document: `backend/docs/google-calendar.md`.

**Interfaces:**
- Consumes existing `current_customer`, `db_session`, customer row lock, `Settings`, `now()`, `uid()`, customer auth, outbox and request idempotency patterns.
- Produces `calendar_routes.router`, `calendar_sync.sync_calendar_batch(settings, session_factory, transport=None) -> dict`, and all exact JSON routes/fields in the spec.
- Settings additions: `calendar_enabled: bool`, `nango_api_key: str` (repr=False), `nango_environment: str='production'`, `nango_allowed_key_fingerprints: str`, `nango_calendar_integration_id: str='estimoto-plus-google-calendar'`.
- Environment names: `GOOGLE_CALENDAR_ENABLED`, `NANGO_API_KEY`, `NANGO_ENVIRONMENT`, `NANGO_ALLOWED_KEY_FINGERPRINTS`, `NANGO_CALENDAR_INTEGRATION_ID`.
- Set `app.state.calendar_transport` for mocked provider tests; never reuse `bridge_transport` to reach Google.

- [ ] **Step 1: Add failing boundary tests with existing TestClient fixtures.**

```python
def test_unconnected_calendar_never_claims_availability(client, customer_headers):
    response = client.post('/v1/calendar/google/availability', headers=customer_headers,
        json={'time_min': future_start(), 'time_max': future_end(),
              'duration_minutes': 60, 'time_zone': 'America/Denver',
              'day_start_hour': 9, 'day_end_hour': 17})
    assert response.status_code in (409, 503)
    assert 'slots' not in response.json()

def test_calendar_status_is_private(client):
    assert client.get('/v1/calendar/google/status').status_code == 401
```

Define `future_start/future_end` as aware UTC now+2days/now+3days in the test file; use existing auth fixtures or define equivalently from the existing tests. Add MockTransport assertions for Nango tags/header fixed paths. Tests must fail on missing routes before implementation.

- [ ] **Step 2: Implement scoped storage, migration, adapter and connection routes.**

Use existing model defaults and transaction conventions. Register model metadata before test `create_all`, add router before static web mount and update `/ready` to the new head. Adapter request headers must be built only from trusted config:

```python
headers = {'Authorization': f'Bearer {settings.nango_api_key}',
           'Provider-Config-Key': settings.nango_calendar_integration_id,
           'Connection-Id': connection.nango_connection_id, 'Retries': '0'}
```

Keep tokens out of exception messages. Validate configured fingerprint/environment and Nango Connect link host. Persist attempts before external writes, use exact immutable tags and generation validation after responses. Implement bounded listing and server-validated selection.

- [ ] **Step 3: Implement availability and request checks.**

Parse all Google intervals as aware datetimes, reject missing/error calendar entries, and use the overlap condition below for the full duration. Iterate timezone-local half-hour candidates inside chosen hours, validate round trips across DST, then serialize UTC start/end.

```python
conflict = any(start < busy_end and end > busy_start
               for busy_start, busy_end in intervals)
```

Add exact optional fields from the spec to draft/directory requests and views. Preserve old hashes by excluding new omitted defaults when computing legacy replay digests. Recheck generation and free/busy at draft, authorization and shop confirmation. Send only readable preferred-time text through the existing bridge; retain structured slots privately.

- [ ] **Step 4: Implement durable app calendar and event synchronization.**

Persist unique source/customer operations and exact payloads before provider mutation. Calendar provision uncertain outcome never automatically posts another calendar. Reconcile via exact app nonce/ownership. Event operations use deterministic IDs, provenance and no attendees/reminders; verify returned ownership/payload after timeout or 409. Scan only explicit calendar-enabled source requests. Handle retries, disconnect generations, cancellations and same-ID reschedules without duplicating bookings. Expose sync issue statuses in request/status views.

```python
event = {'id': operation.event_id, 'summary': operation.title,
         'start': {'dateTime': operation.start.isoformat()},
         'end': {'dateTime': operation.end.isoformat()},
         'reminders': {'useDefault': False},
         'extendedProperties': {'private': {'estimotoPlusOperation': operation.id}}}
```

- [ ] **Step 5: Verify all binding boundaries and commit only task files.**

```sh
cd backend
.venv/bin/python -m pytest tests/test_customer_calendar.py tests/test_calendar_scheduling.py tests/test_calendar_sync.py -q
.venv/bin/python -m pytest -q
```

The report must name tests for forged attempt/connection, late response after disconnect, partial free/busy failure, DST/full duration, changed preference generation, exact old-body replay, uncertain POST recovery and duplicate workers. Include migration upgrade and RLS evidence from disposable PostgreSQL, then commit the backend task. No production OAuth/calendar writes or real shop sends in these tests.

### Task 2: Flutter Calendar and Estibot scheduling UI

**Files:**
- Create: `app/lib/screens/calendar_screen.dart`, `app/lib/widgets/calendar_slot_picker.dart`.
- Modify: `app/pubspec.yaml`, `app/pubspec.lock`, `app/lib/data/repository.dart`, `api_repository.dart`, `demo_repository.dart`, `app/lib/screens/garage_screen.dart`, `estibot_screen.dart`, `shop_outreach_screen.dart`, `request_sheet.dart`, `repairs_screen.dart`, `app/lib/services/customer_workspace.dart`, `app/lib/state/plus_controller.dart`, `app/lib/data/pending_request_store.dart`.
- Test: `app/test/calendar_screen_test.dart`, `app/test/calendar_scheduling_test.dart` and existing account-switch tests as needed.

**Interfaces:**
- Consumes every Task 1 JSON API verb/path/body/response in the spec; read its report for any resolved exact adapter differences.
- Produces repository methods `getCalendarStatus`, `connectGoogleCalendar`, `reconcileGoogleCalendar(String attemptId)`, `listGoogleCalendars`, `saveCalendarPreferences(Json body)`, `findCalendarAvailability(Json body)`, `disconnectGoogleCalendar`, `retryCalendarSync(Json body)`.
- Calendar page uses `WorkspaceState` owner guards. Use default unsupported implementations in `PlusRepository` for older test fakes; API overrides exact endpoints. Demo is local-only and clearly labeled.

- [ ] **Step 1: Add failing widget and repository contract tests.**

```dart
testWidgets('calendar setup explains availability access', (tester) async {
  await tester.pumpWidget(calendarTestApp());
  expect(find.text('Google Calendar'), findsOneWidget);
  expect(find.textContaining('busy'), findsWidgets);
});
```

Define `calendarTestApp` with current app test helpers and a fake repository that supplies disconnected status. Use pinned `timezone: 0.11.1` with embedded IANA data and a central helper; default `Etc/UTC`. Add account-switch tests that deliver a late reconcile/availability response after controller invalidation and verify no prior customer's labels/slots are shown.

- [ ] **Step 2: Implement connection, selection and sync preferences.**

Use the existing http repository sender and url_launcher with validated HTTPS Nango link. Persist only attempt ID in server state, obtain it through status on app return, reconcile at explicit button or lifecycle resume, and never store OAuth tokens. Bind asynchronous result application to the captured active customer. Show unconfigured, reconnect, unavailable and empty-calendar states distinctly. Provide validated IANA time-zone input with common US selections and support custom IANA zones validated server-side. Sync is an explicit customer toggle.

- [ ] **Step 3: Implement shared candidate picker and integrate review flows.**

Date range, duration and business-hour inputs produce the exact availability JSON. Render returned start/end times in the selected time zone with offset; do not guess IANA zone from Dart's abbreviation. Reuse structured UTC results. Capture at most three choices plus generation in immutable outgoing bodies:

```dart
final body = <String, dynamic>{
  ...existingFields,
  'calendar_check': true,
  'duration_minutes': duration,
  'calendar_generation': generation,
  'proposed_slots': selected.map((slot) => slot['start']).toList(),
};
```

Keep selected state and pending request retries deep-frozen, including nested slot arrays. Recheck current customer after every pending-storage await in PlusController.sendRequest; do not attach new optional defaults to restored older bodies. Manual offers remain available without Google, but must not be labeled calendar-checked. Show duration and sync status on review/Repairs. Estibot has a clear Schedule around my calendar action into the same saved-shop/provider request flow, retaining customer review and shop confirmation wording.

- [ ] **Step 4: Validate and commit.**

```sh
cd app
dart format lib test
flutter analyze
flutter test
```

Use mocked URL launcher for OAuth tests, meaningful candidate/selection/account-switch/pending-retry tests, and inspect 390-pixel layout for overflow. Commit only mobile task files. Root handles app version bump and signed release after review.

### Task 3: Provider setup and release verification

**Files:**
- Modify: `docs/release-status.md`, `docs/mobile-release.md`, `README.md`, `app/pubspec.yaml`.
- Create: `docs/releases/2026-09-13-build6.json` (use actual release date/build if changed).
- Private provider config remains only under `~/.config/estimoto-plus/`.

**Interfaces:**
- Consumes reviewed Task 1/2 source, exact Nango integration contract and `scripts/build_live.sh`, `scripts/deploy_live.sh`, `backend/scripts/publish_android_current.py`.
- Produces verified deployed SHA/schema, signed APK/AAB/IPA, permanent Android pointer advanced after public byte verification, ASC processing/group status, and an honest provider readiness report.

- [ ] **Step 1: Verify owned Google OAuth configuration in the user's signed-in Console.**

Calendar API must be enabled, Nango callback registered, exact scopes requested and consent audience verified. Configure the separate integration using protected client secrets only after checking ownership and callback. Do not connect the customer's account without Google consent or claim public readiness from Testing credentials.

- [ ] **Step 2: Run focused regression and independent branch review.**

Backend tests run on SQLite plus disposable PostgreSQL; Flutter analysis/tests and web build pass. Resolve review findings before release. Obtain customer-authorized Google connection if the user completes consent; if unavailable, preserve configured=false/reconnect-required state and state the provider gate explicitly.

- [ ] **Step 3: Commit, push and deploy the exact clean candidate.**

```sh
sh scripts/deploy_live.sh
sh scripts/build_live.sh mobile
```

Verify source SHA and migration head from live `/version` and `/ready`. Check new private endpoints reject unauthenticated traffic and unavailable provider calls fail safely. Verify actual private calendar behavior only with customer consent and clearly distinguish provider mocks from live evidence.

- [ ] **Step 4: Distribute signed artifacts and advance permanent Android link.**

Inspect Android package/version/signing certificate and iOS bundle/build/team before upload. Publish immutable GitHub artifacts, then run the verified Android pointer publisher; download through `/android/download` and hash returned bytes. Upload Plus IPA with ASC_APP_ID=6811678079, wait for VALID, attach internal/external groups; do not interrupt older Apple's pending review. Record exact remaining external review/Google consent gates rather than calling uploaded builds distributed.
