# CRUD gap closure — design

Date: 2026-09-14. Base: `main` at 6268375 (build 10, live).

## Goal

Every customer-owned thing a customer can start in Estimoto + must be finishable, editable and undoable from the app, in live and demo mode, with the same ownership, idempotency and confirmation discipline the existing flows use. This spec closes the gaps found by the 2026-09-14 inventory; it does not add new product surfaces.

Out of scope (deliberately): account deletion and data export, changing the sign-in email, editing calendar bookings after shop confirmation, editing a service request after delivery.

## Gaps closed

| # | Entity | Missing today | After |
| --- | --- | --- | --- |
| 1 | Reminders | edit, delete, un-complete | tap to edit; delete from the editor; "Undo" after complete |
| 2 | Estimate drafts | edit, delete | edit description/claim/date and delete while still a draft |
| 3 | Estimate photos | delete saved photo | delete from the gallery while still a draft; retake by delete + capture |
| 4 | Scheduling requests | discard draft, cancel sent | discard unsent drafts; withdraw sent requests; discard interrupted device drafts |
| 5 | Service history | edit | edit every field from the same editor used to create |
| 6 | Vehicle valuation | nothing persisted for the customer | history of lookups per vehicle, latest shown on open, entries deletable |
| 7 | Demo | drafts can't take photos; calendar can't disconnect; guided capture unimplemented | simple photo picker in demo drafts; disconnect visible; typed demo stub |
| 8 | Assistant | transcript cannot be cleared | "Clear conversation" |
| 9 | Time zone | defaults to Etc/UTC | best-effort device zone when no preference is saved |
| 10 | Assistant copy | unmatched questions get a bare deflection | says what it cannot do and offers the technician search |

## Backend

All new customer routes sit under the existing `/v1` router files, use `current_customer`, `owned(...)`/`_owned_*` lookups, `Strict` schemas, and return the same view dicts the list routes already return. Mutations that touch files remove the file after the row commit, mirroring `delete_vehicle`.

### Reminders (`customer_routes.py`)

- `PUT /v1/reminders/{id}` body `ReminderUpdate` (all `ReminderCreate` fields optional, `exclude_unset`; the date-or-mileage rule is validated on the merged result). 404 when not owned.
- `DELETE /v1/reminders/{id}` → 204.
- `POST /v1/reminders/{id}/reopen` → sets `completed=False`, returns the reminder.

### Estimates (`customer_routes.py`)

An estimate is *editable* when `delivery_status == "draft"` and `status == "draft"` and `processing_state == "not_started"`. Otherwise mutations return 409 `estimate_locked` with detail "This estimate has been shared and can no longer be changed."

- `PUT /v1/estimates/{id}` body `EstimateUpdate` (`description`, `claim_number`, `date_of_loss`, optional; `exclude_unset`).
- `DELETE /v1/estimates/{id}` → 204. Deletes photos rows and files, capture receipts/VIN suggestions for the estimate, then the estimate. Runs inside one transaction; files are removed after commit and failures to unlink are logged, not raised (same as `remove_upload_file`).
- `DELETE /v1/estimates/{id}/photos/{photo_id}` → 204 under the same editability rule. Removes the row then the file.

### Shop outreach (`saved_shops.py`)

- `DELETE /v1/shop-outreach/{id}` → 204 when `status in {"draft", "call_required", "delivery_failed"}`; 409 `outreach_locked` otherwise. Uses `_lock_outreach`.
- `POST /v1/shop-outreach/{id}/withdraw` → when `status in {"queued", "delivery_unknown", "waiting_for_reply"}`: set `status="withdrawn"`, `delivery_status` unchanged, suppress any undelivered outbox row, and invalidate the shop action token so `GET/POST /v1/shop-actions/{token}` render "This request was withdrawn by the customer." 409 when already `confirmed` or terminal. No email is sent to the shop; the review screen says so.

### Knowledge records (`graph.py`)

- `PUT /v1/knowledge/records/{id}` body `KnowledgeRecordUpdate` (all create fields optional, `exclude_unset`). Under `lock_customer`, update the row, delete the record's `GraphEdge` rows and orphaned entities, and re-project exactly as create does. Receipts stay attached. Returns the record view.

### Vehicle valuation (`vehicle_valuation.py`, `valuation_models.py`)

- New table `vehicle_valuation_history`: `id`, `customer_id` (FK, index), `vehicle_id` (FK, index, cascade), `state`, `condition`, `mileage`, `input_hash`, `payload` JSON, `created_at`. Alembic migration `b7f2c9d4e1a0_vehicle_valuation_history`, down_revision `a63e90b72d14`.
- The existing `POST …/valuation` appends a history row on every successful provider or cache result (not on `unavailable`). Cap 50 rows per vehicle; older rows are pruned on insert.
- `GET /v1/vehicles/{id}/valuations` → newest first.
- `DELETE /v1/vehicles/{id}/valuations/{valuation_id}` → 204.

### Assistant (`assistant_model.py`)

Unmatched input returns: "I can't answer that one yet. I can explain an estimate, plan routine maintenance, or find a technician near you." with `intent: "unmatched"` and a `discovery` suggestion for the customer's ZIP when one is saved, so the screen can offer "Find a technician for this".

## Repository layer

`Repository` (abstract) gains, each with a typed `PlusApiException` default so demo overrides stay optional:

```
updateReminder(id, body) · deleteReminder(id) · reopenReminder(id)
updateEstimate(id, body) · deleteEstimate(id) · deletePhoto(estimateId, photoId)
deleteShopOutreach(id) · withdrawShopOutreach(id)
updateKnowledgeRecord(id, body)
listVehicleValuations(vehicleId) · deleteVehicleValuation(vehicleId, valuationId)
```

`ApiRepository` maps each to `_send`. `DemoPlusRepository` implements every one against `_state`, including `openGuidedCapture` returning a typed `GuidedCaptureUnavailable` so nothing throws the base exception, and photo delete for drafts.

`PlusController` gains `clearConversation()`.

## UI

Every destructive action confirms first with the existing dialog shape from `my_shops_screen.dart`; every mutation goes through `runAction`/`perform` so errors surface as readable copy and the snapshot refreshes.

- **Reminders (Garage).** Tapping a reminder opens `_ReminderForm` with the reminder prefilled and a "Delete reminder" action. "Mark reminder complete" shows a snackbar with "Undo" for 6 seconds that calls reopen.
- **Estimates.** Draft detail gets an "Edit details" sheet (same form as create, prefilled) and "Delete draft" in an overflow menu. After sharing, both are hidden and the status line says the estimate is locked. Gallery tiles get a delete icon while the draft is editable.
- **Scheduling requests (My shops).** Draft and call-required cards get "Discard"; queued/waiting cards get "Withdraw request". The review screen shows the same actions. The interrupted-device-draft card gets "Discard draft" beside "Recover", using the receipts recover-or-discard pattern.
- **Service history.** Record cards get "Edit"; `HistoryEditor` takes an optional `record` like `ShopEditor` takes an optional `shop`. Editing an entry that has receipts keeps them and says so.
- **Vehicle value.** On open, load history; show the latest result and a "Past lookups" list with per-row delete. Demo seeds two past lookups so the section is visible.
- **Demo drafts.** Mount `EstimateCaptureGuide` with `recoveryOnly: false` when `controller.isDemo` so camera/gallery buttons appear and photos attach in memory.
- **Calendar (demo).** Show "Disconnect" in demo; it flips the seeded connection off and the screen shows the not-connected state.
- **Estibot.** Overflow "Clear conversation" with confirm. Unmatched replies render the "Find a technician for this" chip.
- **Time zone.** `deviceTimeZone()` in `app/lib/services/time_zone.dart`: on web `Intl.DateTimeFormat().resolvedOptions().timeZone`; on native map `DateTime.now().timeZoneName` for US abbreviations (EST/EDT, CST/CDT, MST/MDT, PST/PDT, AKST/AKDT, HST) to IANA, else null. Used only when no saved preference exists; the saved preference always wins.

## Error handling

- 404 for anything not owned, never 403.
- 409 with a stable `code` for locked estimates and outreach; the app maps both to plain copy ("…can no longer be changed").
- Deletes are idempotent from the client's view: a second delete of a gone row returns 404 and the UI treats 404 after a delete as success.
- File removal failures never fail the request; they are logged with the storage name for the existing cleanup job.

## Tests

Backend (`tests/test_api.py`, `test_saved_shops.py`, `test_knowledge.py`, new `test_valuation_history.py`): each new route has ownership (other customer → 404), happy path, lock/409 rule, and file-removal assertions where a file exists. Migration round-trip via the existing fresh-migration fixture.

Flutter: repository round-trips in `repository_test.dart` for every new demo method; widget tests per screen using the `DemoPlusRepository` subclass harness: reminder edit/delete/undo, estimate edit/delete/photo delete and locked state, outreach discard/withdraw and device-draft discard, history edit keeps receipts, valuation history render/delete, demo photo picker reachable, calendar disconnect in demo, clear conversation, time-zone fallback.

Smokes: extend `scripts/smoke_api.py` with reminder update/delete and estimate delete over the socket.

## Delivery

One branch `feat/crud-gap-closure` from `main`, implemented entity by entity with tests first, merged by fast-forward after `origin/main` is merged in and both suites are green, then deployed with `scripts/deploy_live.sh`. Release notes list the new actions under build 11.
