# Task 1 report: customer Google Calendar backend

Implemented and committed as `363a9b1b2064a4c62496da1d0d7d651a07b4c7d5` on
`feat/customer-app-foundation`. Task base was `9cfd32a0d153dd4844e30c82fc04dcd0a8a55ff3`;
the final candidate also includes the root-owned socket harness commit
`5931b8715b53a1fb9ab2098af3cd048ad798397f`.

Backend work is complete and verified with synthetic providers and disposable
databases. Live Google readiness is a separate gate and remains disabled by
default. This task did not connect a real Google account, access user calendars,
send shop messages, create real events, change provider configuration, or deploy.

## Independent review follow-up

The follow-up commit containing this report update fixes the independent review's
cancellation and confirmation findings. Same-binding cancellation can delete the
exact old copy after a timezone/selection/sync preference change or a prior
reschedule conflict. It still cannot access disconnected/different-account copies.
Proxy GET/DELETE 404 or 410 now require revalidated owned Nango binding and exact
nonce-bearing calendar access before an absent event can be marked removed.
The public confirmation route reads its bounded body asynchronously, then runs the
whole synchronous admission transaction in a worker thread. Extreme timestamp
arithmetic/UTC conversion returns a definite 422 instead of an overflow exception.

The original full-suite command below passed **230 tests, zero skipped, 24.32s**;
the focused PostgreSQL command passed **47 tests, zero skipped, 8.57s**. The socket
smoke again passed with one calendar, one event, one update and one delete. Added
regressions cover changed sync preferences, two cleanup workers, disconnected or
different bindings, conflict-to-cancellation, Nango 404 during both GET and DELETE,
event-loop exclusion during actual shop confirmation, and UTC-boundary timestamps.
These results supersede the initial candidate counts below. Known missing scope
metadata is still a provider-readiness limit: actual capability 401/403 fails
closed into reconnect_required; no claim of live partial-grant verification is made.

## Delivered

- Private customer connection, attempt, provisioning and event-operation tables;
  forward migration `6db7a239f1c8` after `e21870f6a94b`, metadata registration and
  readiness head update. PostgreSQL RLS and privilege revocation cover all four
  private tables. Existing permanent Android download routes remain registered.
- Separate fixed-host Nango adapter with integration/environment/fingerprint
  checks, exact server-authored ownership tags, bounded I/O and response size,
  no redirect following, no raw upstream error text and no credential response.
  Known incomplete scope grants fail verification; Google 401/403 changes the
  current binding to `reconnect_required`, distinct from transient failure.
- All specified `/v1/calendar/google` routes: status, connect, reconcile,
  calendars, preferences, availability, disconnect and explicit one-booking
  sync retry. Foreign and stale attempts cannot bind a connection. Late reads
  and reconcile responses cannot restore a disconnected generation.
- Full-duration free/busy checks, partial-result rejection, IANA/DST handling,
  selected-zone equality, bounded windows/calendars/slots, and inclusion of
  confirmed private Plus appointments even when the app calendar is unselected.
- Optional request/outreach Calendar fields with frozen timezone, generation,
  duration, selected IDs and sync consent. Old omitted fields retain the original
  payload digest. Accepted replay precedes fresh checks. Definite rejected
  directory requests receive durable tombstones and HTTP 422; transient provider
  failure remains HTTP 503. Outreach rechecks at review, authorization, worker
  admission and first shop confirmation.
- Durable app-calendar nonce and claim before POST; uncertain creation only
  reconciles an exact nonce-bearing owned calendar. Stable event operation and
  ID, persisted payload before mutation, exact provenance/payload reconciliation,
  same-ID reschedule and owned-copy cancellation. Six attempts/backoff and
  durable leases bound retries; private indexed scan timestamps prevent older
  pending sources from starving behind the first 100 bookings.
- Customer-row locking serializes admission, bridge updates and Calendar writes
  with preference/disconnect changes. The Plus bridge accepts authenticated
  `scheduled -> scheduled` with distinct event IDs, preserving delivery,
  ownership, replay, aware-time and terminal-state guards.
- Minimal private/opaque Google event with disabled default reminders, no
  attendees/conference/contact/insurance/description and `sendUpdates=none`.
  Calendar labels are private UI metadata and never enter assistant or history
  payloads. The assistant explains the review workflow without claiming access
  or booking success.

Operational/API documentation is in `backend/docs/google-calendar.md`.

## Exact contracts and recovery choices

`POST /v1/calendar/google/sync/retry` accepts
`{source_kind:"request"|"outreach",source_id}` and returns
`{source_kind,source_id,calendar_sync_status,calendar_sync_message}`. It is private,
rate limited to ten per customer per hour, and only accepts an existing checked
confirmed/scheduled source. It rechecks current preferences and free/busy, adopts
that generation for this source, and preserves the frozen confirmed UTC instant,
duration, original review timezone, operation and event ID. It does not import
unrelated historical bookings.

Sync statuses are `not_enabled`, `pending`, `synced`, `conflict`,
`reconnect_required`, `attention_needed`, and `removed`. The booking's own status
remains authoritative when its Calendar copy needs attention.

Reconnecting must preserve a known or uncertain old copy. A new Nango connection
must prove owner access to the exact prior nonce-bearing calendar before adoption.
A different Google account receives a definite rejection; it cannot cause a
second calendar/event copy. A prior definite provider rejection with no created
calendar or applied event can safely retry after repaired authorization.

For an overlapping reschedule, Google free/busy can include the source's own
copy if the app calendar was selected. This release conservatively reports
attention rather than subtracting from a merged busy interval and potentially
hiding another event. The customer can adjust the existing copy or deselect the
app calendar, then explicitly retry. Intentionally deleted known event IDs are
manual attention and are never blindly recreated from Google tombstones.

## Verification

All commands below exited zero on the final backend candidate. The only warning
was the existing Starlette/AnyIO BlockingPortal deprecation.

Full backend suite, from `backend`:

```sh
PLUS_TEST_POSTGRES_URL='postgresql+psycopg://plus_test@127.0.0.1:55439/estimoto_scope_test_plus?client_encoding=utf8' \
ESTIMOTO_BRIDGE_BACKEND='/Users/jamesmcdaniel/Estimoto/.worktrees/plus-launch-integration-20260913/backend' \
ESTIMOTO_BRIDGE_PYTHON='/Users/jamesmcdaniel/Estimoto/backend/.venv/bin/python' \
.venv/bin/python -m pytest -q
```

Result: **220 passed, zero skipped, 23.04 seconds**. This includes the real-source
original Estimoto bridge contract tests, existing PostgreSQL auth tests and new
Calendar tests. Test URLs are local, synthetic credentials only.

All Calendar API and worker cases on isolated PostgreSQL schemas, from `backend`:

```sh
PLUS_TEST_POSTGRES_URL='postgresql+psycopg://plus_test@127.0.0.1:55439/estimoto_scope_test_plus?client_encoding=utf8' \
CALENDAR_TEST_POSTGRES_URL='postgresql+psycopg://plus_test@127.0.0.1:55439/estimoto_scope_test_plus?client_encoding=utf8' \
.venv/bin/python -m pytest tests/test_customer_calendar.py tests/test_calendar_scheduling.py tests/test_calendar_sync.py -q
```

Result: **37 passed, zero skipped, 7.33 seconds**. Each API/worker case uses a
private schema. `test_calendar_migration_and_rls_on_disposable_postgres` creates
a separate disposable database, performs `alembic upgrade head` and
`alembic check`, seeds the four Calendar tables, verifies enabled RLS and denied
SELECT privileges, then explicitly grants a probe role SELECT and proves RLS
still returns zero rows. Its database and role are removed afterward.

Named boundary tests include:

- `test_connect_tags_are_server_owned_and_reconcile_rejects_foreign_attempt`,
  `test_untrusted_connect_link_and_unpinned_key_fail_closed`,
  `test_late_reconcile_cannot_restore_disconnected_connection` and
  `test_late_availability_after_disconnect_is_discarded`.
- `test_partial_or_malformed_freebusy_never_reports_free`,
  `test_truncated_calendar_list_and_partial_scope_fail_closed`,
  `test_revoked_grant_requires_reconnect_without_exposing_provider_body`,
  `test_full_duration_overlap_and_endpoint_touching`,
  `test_dst_weekend_skipped_and_business_hours_use_changed_offset` and
  `test_all_day_busy_and_saved_booking_block_proposals`.
- `test_old_request_body_replays_exact_legacy_digest`,
  `test_checked_request_freezes_private_slots_and_tombstones_definite_conflict`,
  `test_changed_preferences_invalidate_unaccepted_checked_review`,
  `test_outreach_rechecks_busy_at_authorization_and_preserves_old_review` and
  `test_outreach_worker_and_shop_confirmation_recheck_calendar`.
- `test_calendar_creation_and_event_response_loss_reconcile_without_duplicates`,
  `test_two_workers_reschedule_same_event_and_cancel_only_that_event`,
  `test_authenticated_bridge_reschedule_reuses_event_and_preserves_terminal_guard`,
  `test_unrelated_event_id_collision_is_never_overwritten`,
  `test_cancel_after_uncertain_event_does_not_create_delayed_copy` and
  `test_fair_scan_reaches_older_source_beyond_first_hundred`.
- `test_reconnect_adopts_only_verified_existing_calendar_without_cloning`,
  `test_reconnect_to_other_google_account_cannot_clone_old_copy`,
  `test_definite_missing_write_scope_can_recover_without_uncertain_calendar_clone`,
  `test_selected_app_calendar_reschedule_is_conservative_and_retry_keeps_id`,
  `test_intentionally_deleted_known_event_is_not_recreated` and
  `test_private_calendar_labels_never_enter_assistant_or_history`.

Root-owned actual HTTP smoke, rerun against the final backend from repository root:

```sh
backend/.venv/bin/python scripts/smoke_calendar.py
```

Result: **passed**. Local uvicorn HTTP with synthetic Auth, Nango and shop bridge
proved private connect, cross-customer rejection, availability, checked request
replay, bridge delivery, actual accepted/scheduled/rescheduled/cancelled routes,
disconnect and private booking isolation. Recorded counts: **one calendar POST,
one event POST, one same-ID update and one delete**. The harness performs explicit
worker cycles; this proves local application behavior, not live provider delivery.
`git diff --check` passed and the commit's secret scan found no leaks.

## Remaining external gates and limitations

- Root owns Google Console/Nango setup, deployment and customer consent. Verify
  an owned OAuth client, Calendar API enabled, callback
  `https://api.nango.dev/oauth/callback`, production consent audience and exact
  scopes `calendar.calendarlist.readonly`, `calendar.events.freebusy` and
  `calendar.app.created` before setting `GOOGLE_CALENDAR_ENABLED=true` with the
  dedicated Nango configuration and full allowed key fingerprint. Shared/testing
  credentials and synthetic tests do not prove public customer readiness.
- Original staff receiver `plus_bridge.py` previously rejected
  `scheduled -> scheduled`. Root was notified to own that narrow original-side
  change and deployment. This task proves the actual Plus reschedule consumer;
  end-to-end staff UI rescheduling also requires that producer path.
- Disconnect preserves existing Google copies. A provider call already admitted
  under the customer lock may finish before disconnect commits. There is no
  atomic Google free/busy plus event-insert transaction; another Google client
  can change availability after a successful check.
- Conservative overlapping self-copy recovery and intentional deletion behavior
  are documented above. An ambiguous calendar creation never automatically posts
  a replacement calendar. These conditions preserve the source booking and expose
  customer recovery rather than claim successful sync.
- No original Estimoto source, Flutter source, root smoke script or provider
  configuration was edited in this backend commit. No real Google or shop data
  was used by this task's verification.
