# CRUD Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every customer-owned thing in Estimoto + finishable, editable and undoable from the app in live and demo mode: reminders, estimate drafts and photos, scheduling requests, service history, valuation history, plus assistant, calendar and time-zone loose ends.

**Architecture:** Each entity is closed bottom-up in its own task: backend route + `Strict` schema + pytest, then the Flutter repository interface with live (`ApiRepository`) and demo (`DemoPlusRepository`) implementations, then the screen with a confirm dialog and a widget test on the `DemoPlusRepository` harness. Backend mutations reuse `owned()`/`_owned_*` ownership lookups, `lock_customer` row locks, and the existing file-removal helpers. UI mutations go through `runAction`/`perform` so errors render as readable copy and the snapshot refreshes.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + pypdf (Python 3.13, `backend/.venv`), Flutter 3.44.1 / Dart 3.12 (`app/`), pytest and `flutter test`.

**Spec:** `docs/superpowers/specs/2026-09-14-crud-gap-closure-design.md`

## Global Constraints

- Work in the worktree `/Users/jamesmcdaniel/Estimoto--1/.worktrees/crud` on branch `feat/crud-gap-closure`. Never touch the main checkout.
- Backend commands run from `backend/` with `.venv/bin/python -m pytest -q ...`. Flutter commands run from `app/` with `flutter test --no-pub ...` and `flutter analyze --no-pub`.
- Not-owned rows return **404**, never 403. Locked estimates/outreach return **409** with `detail` copy quoted in the task.
- Every delete confirms in the UI first with an `AlertDialog` shaped like `_MyShopsScreenState.remove` in `app/lib/screens/my_shops_screen.dart:116-141`.
- Commit after every task with the `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` trailer. Do not push or deploy; the final task hands that back.
- Run `dart format` on every Dart file you touch before committing.

---

### Task 1: Reminder update, delete and reopen (backend)

**Files:**
- Modify: `backend/estimoto_plus/schemas.py:75-85` (after `ReminderCreate`)
- Modify: `backend/estimoto_plus/customer_routes.py:478-495` (after `complete_reminder`)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `PUT /v1/reminders/{id}` body `{title?, due_date?, due_mileage?, vehicle_id?}` → reminder view; `DELETE /v1/reminders/{id}` → 204; `POST /v1/reminders/{id}/reopen` → reminder view with `completed: false`.

- [ ] **Step 1: Write the failing tests**

Find how `tests/test_api.py` creates a client, a vehicle and headers (look for `create_vehicle`, `h("alice")`, and an existing reminder test) and append:

```python
def test_reminder_update_delete_and_reopen(clients):
    client, _ = clients
    vid = create_vehicle(client)
    made = client.post("/v1/reminders", json={"vehicle_id": vid, "title": "Oil", "due_mileage": 1000}, headers=h("alice"))
    assert made.status_code == 201
    rid = made.json()["id"]
    updated = client.put(f"/v1/reminders/{rid}", json={"title": "Oil and filter", "due_date": "2027-01-15"}, headers=h("alice"))
    assert updated.status_code == 200
    assert updated.json()["title"] == "Oil and filter" and updated.json()["due_date"] == "2027-01-15"
    assert updated.json()["due_mileage"] == 1000
    # The date-or-mileage rule holds on the merged result.
    assert client.put(f"/v1/reminders/{rid}", json={"due_date": None, "due_mileage": None}, headers=h("alice")).status_code == 422
    assert client.post(f"/v1/reminders/{rid}/complete", headers=h("alice")).json()["completed"] is True
    assert client.post(f"/v1/reminders/{rid}/reopen", headers=h("alice")).json()["completed"] is False
    # Another customer sees nothing.
    assert client.put(f"/v1/reminders/{rid}", json={"title": "x"}, headers=h("bob")).status_code == 404
    assert client.delete(f"/v1/reminders/{rid}", headers=h("bob")).status_code == 404
    assert client.post(f"/v1/reminders/{rid}/reopen", headers=h("bob")).status_code == 404
    assert client.delete(f"/v1/reminders/{rid}", headers=h("alice")).status_code == 204
    assert client.delete(f"/v1/reminders/{rid}", headers=h("alice")).status_code == 404
    assert all(r["id"] != rid for r in client.get("/v1/bootstrap", headers=h("alice")).json()["reminders"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_api.py -k reminder_update`
Expected: FAIL with `assert 405 == 200` (or 404) on the PUT.

- [ ] **Step 3: Add the schema**

In `schemas.py` after `ReminderCreate`:

```python
class ReminderUpdate(Strict):
    vehicle_id: str | None = Field(default=None, max_length=36)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: Date | None = None
    due_mileage: int | None = Field(default=None, ge=0, le=5_000_000)
```

- [ ] **Step 4: Add the routes**

In `customer_routes.py` after `complete_reminder`, importing `ReminderUpdate` alongside `ReminderCreate`:

```python
@router.put("/reminders/{reminder_id}")
def update_reminder(reminder_id: str, body: ReminderUpdate, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    r = owned(db, Reminder, reminder_id, c)
    changes = body.model_dump(exclude_unset=True)
    if "vehicle_id" in changes:
        owned(db, Vehicle, changes["vehicle_id"], c)
    if "due_date" in changes:
        changes["due_date"] = iso(changes["due_date"])
    merged_date = changes.get("due_date", r.due_date)
    merged_mileage = changes.get("due_mileage", r.due_mileage)
    if merged_date is None and merged_mileage is None:
        raise HTTPException(422, "A date or mileage is required.")
    for k, val in changes.items():
        setattr(r, k, val)
    db.commit()
    return reminder_view(r)


@router.delete("/reminders/{reminder_id}", status_code=204)
def delete_reminder(reminder_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    r = owned(db, Reminder, reminder_id, c)
    db.delete(r)
    db.commit()


@router.post("/reminders/{reminder_id}/reopen")
def reopen_reminder(reminder_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    r = owned(db, Reminder, reminder_id, c)
    r.completed = False
    db.commit()
    return reminder_view(r)
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_api.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/estimoto_plus/schemas.py backend/estimoto_plus/customer_routes.py backend/tests/test_api.py
git commit -m "Add reminder update, delete and reopen routes"
```

---

### Task 2: Estimate draft edit, delete and photo delete (backend)

**Files:**
- Modify: `backend/estimoto_plus/schemas.py:61-67` (after `EstimateCreate`)
- Modify: `backend/estimoto_plus/customer_routes.py:321-330` (after `create_estimate`) and `:466-475` (after `get_photo`)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `PUT /v1/estimates/{id}` body `{description?, claim_number?, date_of_loss?}` → estimate view; `DELETE /v1/estimates/{id}` → 204; `DELETE /v1/estimates/{id}/photos/{photo_id}` → 204. Locked → 409 `{"detail": "This estimate has been shared and can no longer be changed.", "code": "estimate_locked"}`.

- [ ] **Step 1: Write the failing tests**

Look at how the existing photo upload test builds an image (`image()` helper or PIL) and how a submitted estimate is created in tests (search `submit` in `tests/test_api.py` or `tests/test_estimate_*.py`). Append to `tests/test_api.py`:

```python
def test_estimate_draft_edit_delete_and_photo_delete(clients, tmp_path):
    client, _ = clients
    vid = create_vehicle(client)
    e = client.post("/v1/estimates", json={"vehicle_id": vid, "discipline": "pdr", "description": "Door ding"}, headers=h("alice")).json()
    eid = e["id"]
    edited = client.put(f"/v1/estimates/{eid}", json={"description": "Two door dings", "claim_number": "CLM-1"}, headers=h("alice"))
    assert edited.status_code == 200 and edited.json()["description"] == "Two door dings" and edited.json()["claim_number"] == "CLM-1"
    assert client.put(f"/v1/estimates/{eid}", json={"description": "x"}, headers=h("bob")).status_code == 404
    photo = client.post(f"/v1/estimates/{eid}/photos", files={"file": ("a.jpg", image(), "image/jpeg")}, data={"label": "front"}, headers=h("alice"))
    assert photo.status_code == 201
    pid = photo.json()["id"]
    settings = client.app.state.settings
    from estimoto_plus.models import Photo
    with client.app.state.session_factory() as db:
        storage = db.get(Photo, pid).storage_name
    assert (Path(settings.photo_dir) / storage).is_file()
    assert client.delete(f"/v1/estimates/{eid}/photos/{pid}", headers=h("bob")).status_code == 404
    assert client.delete(f"/v1/estimates/{eid}/photos/{pid}", headers=h("alice")).status_code == 204
    assert not (Path(settings.photo_dir) / storage).exists()
    assert client.get(f"/v1/estimates/{eid}/photos/{pid}", headers=h("alice")).status_code == 404
    # A second photo is removed together with the draft.
    pid2 = client.post(f"/v1/estimates/{eid}/photos", files={"file": ("b.jpg", image(), "image/jpeg")}, data={"label": "rear"}, headers=h("alice")).json()["id"]
    with client.app.state.session_factory() as db:
        storage2 = db.get(Photo, pid2).storage_name
    assert client.delete(f"/v1/estimates/{eid}", headers=h("bob")).status_code == 404
    assert client.delete(f"/v1/estimates/{eid}", headers=h("alice")).status_code == 204
    assert not (Path(settings.photo_dir) / storage2).exists()
    assert all(item["id"] != eid for item in client.get("/v1/bootstrap", headers=h("alice")).json()["estimates"])
    # The vehicle is no longer pinned by the abandoned draft.
    assert client.delete(f"/v1/vehicles/{vid}", headers=h("alice")).status_code == 204


def test_shared_estimate_is_locked(clients):
    client, _ = clients
    vid = create_vehicle(client)
    eid = client.post("/v1/estimates", json={"vehicle_id": vid, "discipline": "pdr", "description": "x"}, headers=h("alice")).json()["id"]
    from estimoto_plus.models import Estimate
    with client.app.state.session_factory() as db:
        row = db.get(Estimate, eid)
        row.delivery_status = "queued"
        db.commit()
    for response in (client.put(f"/v1/estimates/{eid}", json={"description": "y"}, headers=h("alice")),
                     client.delete(f"/v1/estimates/{eid}", headers=h("alice"))):
        assert response.status_code == 409
        assert response.json()["detail"] == "This estimate has been shared and can no longer be changed."
        assert response.json()["code"] == "estimate_locked"
```

If `tests/test_api.py` has no `image()` helper, add `from tests.test_receipts import image` or copy the two-line PIL JPEG generator used there. Import `Path` from `pathlib` at the top if missing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_api.py -k "estimate_draft or estimate_is_locked"`
Expected: FAIL on the PUT with 405/404.

- [ ] **Step 3: Add the schema**

```python
class EstimateUpdate(Strict):
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    claim_number: str | None = Field(default=None, max_length=100)
    date_of_loss: Date | None = None
```

- [ ] **Step 4: Add the lock helper and routes**

In `customer_routes.py`, next to `owned()`:

```python
def editable_estimate(db, estimate_id, customer):
    e = owned(db, Estimate, estimate_id, customer)
    if e.delivery_status != "draft" or e.status != "draft" or e.processing_state != "not_started":
        raise HTTPException(409, {"detail": "This estimate has been shared and can no longer be changed.", "code": "estimate_locked"})
    return e
```

Check how the app's HTTP exception handler in `app.py` serializes a dict `detail`: if the handler only passes `detail` through, use `HTTPException(409, "This estimate has been shared and can no longer be changed.", headers={"X-Error-Code": "estimate_locked"})` and adjust the test to read the header instead. Look for an existing `code` pattern (search `"code":` in `customer_routes.py` around request rejections) and copy exactly that shape so the Flutter `PlusApiException.code` decoding in `api_repository.dart:127-186` picks it up.

After `create_estimate`:

```python
@router.put("/estimates/{estimate_id}")
def update_estimate(estimate_id: str, body: EstimateUpdate, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    e = editable_estimate(db, estimate_id, c)
    changes = body.model_dump(exclude_unset=True)
    if "date_of_loss" in changes:
        changes["date_of_loss"] = iso(changes["date_of_loss"])
    for k, val in changes.items():
        setattr(e, k, val)
    e.updated_at = now()
    db.commit()
    return estimate_view(db, e)


@router.delete("/estimates/{estimate_id}", status_code=204)
def delete_estimate(estimate_id: str, request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    e = editable_estimate(db, estimate_id, c)
    from .capture_models import CaptureReceipt, CaptureVinSuggestion
    photos = db.scalars(select(Photo).where(Photo.estimate_id == e.id)).all()
    names = [p.storage_name for p in photos]
    for p in photos:
        db.delete(p)
    db.execute(delete(CaptureReceipt).where(CaptureReceipt.estimate_id == e.id))
    db.execute(delete(CaptureVinSuggestion).where(CaptureVinSuggestion.estimate_id == e.id))
    db.delete(e)
    db.commit()
    from .vehicle_images import remove_upload_file
    for name in names:
        remove_upload_file(request.app.state.settings, name)
```

Check `capture_models.py` for any other table with `estimate_id` (the inventory found `CaptureReceipt` and `CaptureVinSuggestion`) and add it to the delete list. Confirm `delete` is imported from `sqlalchemy` at the top of `customer_routes.py`.

After `get_photo`:

```python
@router.delete("/estimates/{estimate_id}/photos/{photo_id}", status_code=204)
def delete_photo(estimate_id: str, photo_id: str, request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    editable_estimate(db, estimate_id, c)
    p = db.get(Photo, photo_id)
    if not p or p.estimate_id != estimate_id:
        raise HTTPException(404, "Not found.")
    name = p.storage_name
    db.delete(p)
    db.commit()
    from .vehicle_images import remove_upload_file
    remove_upload_file(request.app.state.settings, name)
```

Read `remove_upload_file` in `vehicle_images.py` first; if it only accepts image storage names under a subfolder, add a sibling `remove_photo_file(settings, storage_name)` that unlinks `Path(settings.photo_dir) / storage_name` inside `try/except OSError` with a `logging.getLogger(__name__).warning(...)`, and use that.

- [ ] **Step 5: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_api.py tests/test_capture*.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/estimoto_plus backend/tests/test_api.py
git commit -m "Let customers edit and delete unshared estimate drafts and their photos"
```

---

### Task 3: Scheduling request discard and withdraw (backend)

**Files:**
- Modify: `backend/estimoto_plus/saved_shops.py:234-262` (after `get_outreach`), `:363-400` (`_action_record` / landing)
- Test: `backend/tests/test_saved_shops.py`

**Interfaces:**
- Produces: `DELETE /v1/shop-outreach/{id}` → 204 for `status in {"draft", "call_required", "delivery_failed"}`, else 409 `"This request was already sent and can only be withdrawn."`; `POST /v1/shop-outreach/{id}/withdraw` → outreach view with `status: "withdrawn"` for `status in {"queued", "delivery_unknown", "waiting_for_reply"}`, else 409 `"This request can no longer be withdrawn."`. The shop landing for a withdrawn token renders "This request was withdrawn by the customer." with HTTP 410.

- [ ] **Step 1: Write the failing tests**

Read the top of `tests/test_saved_shops.py` for the helpers that create a shop, a draft and authorize it (search `def draft(` / `authorize`). Append:

```python
def test_outreach_draft_can_be_discarded(clients):
    client, _ = clients
    shop = create_shop(client)
    d = create_draft(client, shop["id"])
    assert client.delete(f"/v1/shop-outreach/{d['id']}", headers=h("bob")).status_code == 404
    assert client.delete(f"/v1/shop-outreach/{d['id']}", headers=h("alice")).status_code == 204
    assert client.get(f"/v1/shop-outreach/{d['id']}", headers=h("alice")).status_code == 404
    assert all(row["id"] != d["id"] for row in client.get("/v1/shop-outreach", headers=h("alice")).json())


def test_sent_outreach_can_be_withdrawn_and_shop_link_dies(clients):
    client, _ = clients
    shop = create_shop(client)
    d = create_draft(client, shop["id"])
    sent = authorize_draft(client, d)              # status becomes "queued"
    assert client.delete(f"/v1/shop-outreach/{d['id']}", headers=h("alice")).status_code == 409
    withdrawn = client.post(f"/v1/shop-outreach/{d['id']}/withdraw", headers=h("alice"))
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "withdrawn"
    assert client.post(f"/v1/shop-outreach/{d['id']}/withdraw", headers=h("alice")).status_code == 409
    token = shop_action_token_for(client, d["id"])  # helper: read the raw token the test transport captured, or mint one via the same function the sender uses
    landing = client.get(f"/v1/shop-actions/{token}")
    assert landing.status_code == 410 and "withdrawn by the customer" in landing.text
    assert client.post(f"/v1/shop-actions/{token}", data={"slot": d["proposed_slots"][0]},
                       headers={"content-type": "application/x-www-form-urlencoded"}).status_code == 410
```

Write `shop_action_token_for` the same way the existing confirmation tests obtain the token (they capture the outgoing email through the injected transport; grep `action_token` in the test file and reuse that mechanism). If drafts are authorized via a test fixture that delivers synchronously, call the same fixture.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_saved_shops.py -k "discarded or withdrawn"`
Expected: FAIL with 405 on DELETE.

- [ ] **Step 3: Add the routes**

After `get_outreach` in `saved_shops.py`:

```python
DISCARDABLE = {"draft", "call_required", "delivery_failed"}
WITHDRAWABLE = {"queued", "delivery_unknown", "waiting_for_reply"}


@router.delete("/shop-outreach/{outreach_id}", status_code=204)
def discard_outreach(outreach_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    _lock_outreach(db, outreach_id)
    outreach = _owned_outreach(db, outreach_id, c.id)
    if outreach.status not in DISCARDABLE:
        raise HTTPException(409, "This request was already sent and can only be withdrawn.")
    db.execute(delete(ShopOutbox).where(ShopOutbox.outreach_id == outreach.id))
    db.delete(outreach)
    db.commit()


@router.post("/shop-outreach/{outreach_id}/withdraw")
def withdraw_outreach(outreach_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    _lock_outreach(db, outreach_id)
    outreach = _owned_outreach(db, outreach_id, c.id)
    if outreach.status not in WITHDRAWABLE:
        raise HTTPException(409, "This request can no longer be withdrawn.")
    outreach.status = "withdrawn"
    outreach.action_expires_at = now()
    outreach.updated_at = now()
    pending = db.scalar(select(ShopOutbox).where(ShopOutbox.outreach_id == outreach.id, ShopOutbox.finished_at.is_(None)))
    if pending is not None:
        pending.finished_at = now()
    db.commit()
    return _outreach_view(outreach)
```

Confirm `delete` and `select` are imported from `sqlalchemy` and `ShopOutbox` from `.shop_models` at the top. Check how the outbox deliverer selects due rows (`deliver` function near line 450): if it filters on `finished_at IS NULL`, the above is enough; if it filters on `claim_token`/`next_attempt_at`, also set `next_attempt_at` far in the future and add a status check in the deliverer so a withdrawn outreach is skipped with `finished_at = now()`.

In `_action_record` (line 363) after the record lookup, before the status checks in both landing and confirm:

```python
    if record.status == "withdrawn":
        raise HTTPException(410, "This request was withdrawn by the customer.")
```

and make the landing's 404 for "Action link not available." remain for other states. Verify the HTML error handler renders the 410 detail text (the test asserts the phrase appears in `landing.text`); if the app returns JSON for `HTTPException` on this route, return `HTMLResponse(f"<p>{html.escape(detail)}</p>", status_code=410, headers=...)` explicitly with the same CSP headers the landing uses.

Add `"withdrawn": "Withdrawn"` wherever `_outreach_view` or status label maps exist in the backend (grep `waiting_for_reply` in `saved_shops.py` and `estimoto_plus/*.py` for label tables).

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_saved_shops.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/estimoto_plus/saved_shops.py backend/tests/test_saved_shops.py
git commit -m "Let customers discard unsent scheduling drafts and withdraw sent requests"
```

---

### Task 4: Service history record update with graph re-projection (backend)

**Files:**
- Modify: `backend/estimoto_plus/graph.py:183` (before `delete_record`)
- Test: `backend/tests/test_knowledge.py`

**Interfaces:**
- Produces: `PUT /v1/knowledge/records/{id}` body: any subset of `RecordInput` fields except `vehicle_id` is optional too → record view. Receipts untouched. Graph edges for the record rebuilt.

- [ ] **Step 1: Write the failing test**

Read the top of `tests/test_knowledge.py` for `add(...)`, `create_vehicle`, `h`. Append:

```python
def test_history_record_update_keeps_receipts_and_reprojects_graph(clients):
    client, _ = clients
    vid = create_vehicle(client)
    record = add(client, vid, shop_name="Old Shop", parts_source="Old Parts").json()
    rid = record["id"]
    from tests.test_receipts import upload
    assert upload(client, rid).status_code == 201
    updated = client.put(f"/v1/knowledge/records/{rid}", json={"shop_name": "New Shop", "cost_cents": 12345, "notes": "changed"}, headers=h("alice"))
    assert updated.status_code == 200
    body = updated.json()
    assert body["shop_name"] == "New Shop" and body["cost_cents"] == 12345 and body["notes"] == "changed"
    assert body["parts_source"] == "Old Parts" and len(body["receipts"]) == 1
    graph = client.get("/v1/knowledge/graph", headers=h("alice")).json()
    labels = {e["label"] for e in graph["entities"]}
    assert "New Shop" in labels and "Old Shop" not in labels
    assert client.put(f"/v1/knowledge/records/{rid}", json={"shop_name": "x"}, headers=h("bob")).status_code == 404
    assert client.put(f"/v1/knowledge/records/{rid}", json={"service_date": "not-a-date"}, headers=h("alice")).status_code == 422
```

Adjust `add(...)` keyword names to what the helper accepts; if it takes a dict, pass `{"shop_name": ..., "parts_source": ...}`. Read `own_graph` (`graph.py:209`) for the exact response keys (`entities`/`edges`) and match them.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_knowledge.py -k record_update`
Expected: FAIL with 405.

- [ ] **Step 3: Add the schema and route**

In `graph.py`, `RecordInput` is defined near the top; add below it:

```python
class RecordUpdate(Strict):
    service_type: RecordInput.model_fields["service_type"].annotation | None = None
    service_date: RecordInput.model_fields["service_date"].annotation | None = None
    mileage: int | None = Field(default=None, ge=0, le=5_000_000)
    cost_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    shop_name: str | None = Field(default=None, max_length=200)
    parts_source: str | None = Field(default=None, max_length=200)
    parts_description: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)
```

If `RecordInput` uses validators (date format, `Literal` service types), reuse them explicitly rather than the `model_fields[...]` trick: copy the same `Literal[...]` and the same `field_validator` for `service_date` onto `RecordUpdate`.

Route, placed before `delete_record`:

```python
@router.put("/v1/knowledge/records/{record_id}")
def update_record(record_id: str, body: RecordUpdate, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    lock_customer(db, c.id)
    record = db.get(KnowledgeRecord, record_id)
    if record is None or record.customer_id != c.id:
        raise HTTPException(404, "History not found.")
    from .customer_routes import consume_rate
    consume_rate(db, c.id, "knowledge_update", 60)
    for k, val in body.model_dump(exclude_unset=True).items():
        setattr(record, k, val)
    db.flush()
    db.execute(delete(GraphEdge).where(GraphEdge.customer_id == c.id, GraphEdge.record_id == record.id))
    db.flush()
    linked = select(GraphEdge.id).where(GraphEdge.customer_id == c.id,
                                      or_(GraphEdge.from_id == GraphEntity.id, GraphEdge.to_id == GraphEntity.id)).exists()
    db.execute(delete(GraphEntity).where(GraphEntity.customer_id == c.id, ~linked))
    vehicle = db.get(Vehicle, record.vehicle_id)
    project_record(db, record, vehicle)
    db.commit()
    return record_view(record)
```

Read `project_record` (`graph.py:126`) to confirm it creates the service entity keyed by record id and reuses `graph_entity` for shared nodes, so re-running it after the edge purge yields exactly the create-time graph.

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_knowledge.py tests/test_receipts.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/estimoto_plus/graph.py backend/tests/test_knowledge.py
git commit -m "Let customers edit service history records with graph re-projection"
```

---

### Task 5: Vehicle valuation history (backend, migration)

**Files:**
- Modify: `backend/estimoto_plus/valuation_models.py`
- Create: `backend/alembic/versions/b7f2c9d4e1a0_vehicle_valuation_history.py`
- Modify: `backend/estimoto_plus/vehicle_valuation.py:211-277`
- Create: `backend/tests/test_valuation_history.py`

**Interfaces:**
- Produces: table `vehicle_valuation_history`; `GET /v1/vehicles/{id}/valuations` → `{"vehicle_id": ..., "valuations": [{id, state, condition, mileage, created_at, payload}]}` newest first; `DELETE /v1/vehicles/{id}/valuations/{valuation_id}` → 204. `POST …/valuation` appends a row on every response with `status == "available"` (provider or cache), pruned to 50 per vehicle.

- [ ] **Step 1: Write the failing test**

Read `tests/test_vehicle_valuation.py` for the fixture that stubs the CarsXE transport (search `transport` / `fetch_valuation`) and how it creates a vehicle with a 17-char VIN. Create `tests/test_valuation_history.py`:

```python
from tests.test_vehicle_valuation import clients, valued_vehicle, h  # reuse: fixtures for a client with a stubbed provider and a VIN-complete vehicle


def test_valuation_lookups_are_kept_per_vehicle_and_deletable(clients, valued_vehicle):
    client = clients[0]
    vid = valued_vehicle
    first = client.post(f"/v1/vehicles/{vid}/valuation", json={"state": "CO", "condition": "average"}, headers=h("alice"))
    assert first.status_code == 200 and first.json()["status"] == "available"
    second = client.post(f"/v1/vehicles/{vid}/valuation", json={"state": "CO", "condition": "average"}, headers=h("alice"))
    assert second.json()["cached"] is True
    listed = client.get(f"/v1/vehicles/{vid}/valuations", headers=h("alice"))
    assert listed.status_code == 200
    rows = listed.json()["valuations"]
    assert len(rows) == 2 and rows[0]["created_at"] >= rows[1]["created_at"]
    assert rows[0]["state"] == "CO" and rows[0]["condition"] == "average" and rows[0]["payload"]["buckets"]
    assert client.get(f"/v1/vehicles/{vid}/valuations", headers=h("bob")).status_code == 404
    assert client.delete(f"/v1/vehicles/{vid}/valuations/{rows[0]['id']}", headers=h("bob")).status_code == 404
    assert client.delete(f"/v1/vehicles/{vid}/valuations/{rows[0]['id']}", headers=h("alice")).status_code == 204
    assert len(client.get(f"/v1/vehicles/{vid}/valuations", headers=h("alice")).json()["valuations"]) == 1


def test_valuation_history_is_capped_at_fifty(clients, valued_vehicle):
    client = clients[0]
    vid = valued_vehicle
    from estimoto_plus.valuation_models import VehicleValuationHistory
    with client.app.state.session_factory() as db:
        for i in range(55):
            db.add(VehicleValuationHistory(customer_id="alice", vehicle_id=vid, state="CO", condition="average",
                                           mileage=1000 + i, input_hash="x" * 64, payload={"buckets": []}))
        db.commit()
    assert client.post(f"/v1/vehicles/{vid}/valuation", json={"state": "CO", "condition": "average"}, headers=h("alice")).status_code == 200
    assert len(client.get(f"/v1/vehicles/{vid}/valuations", headers=h("alice")).json()["valuations"]) == 50
```

Use the real customer id the fixture assigns to "alice" (read the fixture; it may be `"alice"` or a UUID) for `customer_id=`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_valuation_history.py`
Expected: FAIL with ImportError for `VehicleValuationHistory`.

- [ ] **Step 3: Add the model**

Append to `valuation_models.py`:

```python
class VehicleValuationHistory(Base):
    __tablename__ = 'vehicle_valuation_history'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey('customers.id', ondelete='CASCADE'), index=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('vehicles.id', ondelete='CASCADE'), index=True)
    state: Mapped[str] = mapped_column(String(2))
    condition: Mapped[str] = mapped_column(String(20))
    mileage: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
```

Import `uid` and `now` from `.models` (they exist there; check the names at `models.py` top).

- [ ] **Step 4: Add the migration**

```python
"""Private per-vehicle valuation history.

Revision ID: b7f2c9d4e1a0
Revises: a63e90b72d14
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7f2c9d4e1a0'
down_revision = 'a63e90b72d14'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('vehicle_valuation_history',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('customer_id', sa.String(100), sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('vehicle_id', sa.String(36), sa.ForeignKey('vehicles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('state', sa.String(2), nullable=False),
        sa.Column('condition', sa.String(20), nullable=False),
        sa.Column('mileage', sa.Integer(), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_vehicle_valuation_history_customer_id', 'vehicle_valuation_history', ['customer_id'])
    op.create_index('ix_vehicle_valuation_history_vehicle_id', 'vehicle_valuation_history', ['vehicle_id'])


def downgrade():
    op.drop_table('vehicle_valuation_history')
```

Check `backend/tests/conftest.py` for how tests build the schema (Alembic upgrade vs `Base.metadata.create_all`). If Alembic, the migration must exist for tests to pass; run `DATABASE_URL=sqlite:///$(mktemp).db .venv/bin/alembic upgrade head && .venv/bin/alembic check` from `backend/` to confirm the model and migration agree. Look at `models.py` `__table_args__` conventions and any RLS/grant statements in the previous migration (`a63e90b72d14`) that must be replicated for the restricted PostgreSQL role, and replicate them for the new table.

- [ ] **Step 5: Record history in the lookup and add the routes**

In `vehicle_valuation.py`, add a helper near `response(...)`:

```python
def record_history(db, customer_id, vehicle_id, snapshot, digest, payload):
    db.add(VehicleValuationHistory(customer_id=customer_id, vehicle_id=vehicle_id, state=snapshot['state'],
                                   condition=snapshot['condition'], mileage=snapshot['mileage'],
                                   input_hash=digest, payload=payload))
    db.flush()
    ids = db.scalars(select(VehicleValuationHistory.id).where(VehicleValuationHistory.vehicle_id == vehicle_id)
                     .order_by(VehicleValuationHistory.created_at.desc(), VehicleValuationHistory.id.desc()).offset(50)).all()
    if ids:
        db.execute(delete(VehicleValuationHistory).where(VehicleValuationHistory.id.in_(ids)))
```

Call it in `valuation()` in the two places that return `status='available'`: the cache-hit branch (before `return response(...)`, only when `entry.payload` is truthy, followed by `db.commit()`) and the provider-success branch (right before the final `db.commit()`, only when `result.payload`). Then add:

```python
def history_view(row):
    return {'id': row.id, 'state': row.state, 'condition': row.condition, 'mileage': row.mileage,
            'created_at': row.created_at.isoformat(), 'payload': row.payload}


@router.get('/{vehicle_id}/valuations')
def list_valuations(vehicle_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned(db, Vehicle, vehicle_id, c)
    rows = db.scalars(select(VehicleValuationHistory).where(VehicleValuationHistory.customer_id == c.id,
                                                            VehicleValuationHistory.vehicle_id == vehicle_id)
                      .order_by(VehicleValuationHistory.created_at.desc(), VehicleValuationHistory.id.desc())).all()
    return {'vehicle_id': vehicle_id, 'valuations': [history_view(r) for r in rows]}


@router.delete('/{vehicle_id}/valuations/{valuation_id}', status_code=204)
def delete_valuation(vehicle_id: str, valuation_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned(db, Vehicle, vehicle_id, c)
    row = db.get(VehicleValuationHistory, valuation_id)
    if row is None or row.customer_id != c.id or row.vehicle_id != vehicle_id:
        raise HTTPException(404, 'Not found.')
    db.delete(row)
    db.commit()
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_valuation_history.py tests/test_vehicle_valuation.py tests/test_migrations*.py`
Expected: all pass (PostgreSQL-only cases still skip).

- [ ] **Step 7: Commit**

```bash
git add backend/estimoto_plus/valuation_models.py backend/estimoto_plus/vehicle_valuation.py backend/alembic/versions/b7f2c9d4e1a0_vehicle_valuation_history.py backend/tests/test_valuation_history.py
git commit -m "Keep a private per-vehicle valuation history"
```

---

### Task 6: Assistant unmatched reply names its limits (backend)

**Files:**
- Modify: `backend/estimoto_plus/customer_routes.py:553`
- Test: `backend/tests/test_api.py` (or wherever `/v1/assistant` is tested; grep `assistant`)

**Interfaces:**
- Produces: for unmatched input the response has `intent: "unmatched"`, the reply below, and `discovery: {"postal_code": <saved ZIP or null>, "specialty": null}`.

- [ ] **Step 1: Write the failing test**

```python
def test_assistant_unmatched_reply_names_limits_and_offers_search(clients):
    client, _ = clients
    client.put("/v1/profile", json={"name": "A", "postal_code": "80202"}, headers=h("alice"))
    answer = client.post("/v1/assistant", json={"message": "my check engine light is on and the car shakes"}, headers=h("alice")).json()
    assert answer["intent"] == "unmatched"
    assert answer["reply"] == "I can't answer that one yet. I can explain an estimate, plan routine maintenance, or find a technician near you."
    assert answer["discovery"]["postal_code"] == "80202"
```

Read the existing assistant tests first: if an existing test asserts the old sentence, update that assertion in the same commit. Read `customer_routes.py:496-597` to see what `intent` and `discovery` keys the deterministic path already returns and match the shape exactly (do not invent a second field name).

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest -q tests -k assistant_unmatched`
Expected: FAIL on `intent`.

- [ ] **Step 3: Change the fallback branch**

At `customer_routes.py:553` replace the reply and set the intent:

```python
        reply = "I can't answer that one yet. I can explain an estimate, plan routine maintenance, or find a technician near you."
        intent = "unmatched"
        discovery = {"postal_code": c.postal_code or None, "specialty": None}
```

and make sure those variables flow into the returned dict the same way the matched branches do (read the surrounding code; the matched branches already build `discovery` for provider searches).

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/estimoto_plus/customer_routes.py backend/tests
git commit -m "Say what Estibot cannot answer and offer the technician search"
```

---

### Task 7: Flutter data layer for every new operation

**Files:**
- Modify: `app/lib/data/repository.dart:15-121`
- Modify: `app/lib/data/api_repository.dart` (next to the sibling methods at `:270-280`, `:393-410`, `:445-460`, `:536-560`, `:574-592`)
- Modify: `app/lib/data/demo_repository.dart` (next to the sibling methods at `:396`, `:445-470`, `:520-540`, `:655-680`; outreach at `:322-390`)
- Modify: `app/lib/state/plus_controller.dart:58-66`
- Test: `app/test/repository_test.dart`

**Interfaces (exact names later tasks use):**

```dart
Future<Json> updateReminder(String id, Json body);
Future<void> deleteReminder(String id);
Future<Json> reopenReminder(String id);
Future<Json> updateEstimate(String id, Json body);
Future<void> deleteEstimate(String id);
Future<void> deletePhoto(String estimateId, String photoId);
Future<void> deleteShopOutreach(String id);
Future<Json> withdrawShopOutreach(String id);
Future<Json> updateKnowledgeRecord(String id, Json body);
Future<Json> listVehicleValuations(String vehicleId);      // {'vehicle_id', 'valuations': [...]}
Future<void> deleteVehicleValuation(String vehicleId, String valuationId);
// PlusController
void clearConversation();
```

- [ ] **Step 1: Write the failing repository tests**

Append to `app/test/repository_test.dart` inside `main()`:

```dart
  test('demo reminders can be edited, reopened and deleted', () async {
    final repository = DemoPlusRepository();
    final vehicle = (await repository.bootstrap()).vehicles.first;
    final made = await repository.addReminder({
      'vehicle_id': vehicle.id,
      'title': 'Oil',
      'due_mileage': 1000,
    });
    final id = made['id'] as String;
    final edited = await repository.updateReminder(id, {'title': 'Oil and filter'});
    expect(edited['title'], 'Oil and filter');
    expect(edited['due_mileage'], 1000);
    await repository.completeReminder(id);
    expect((await repository.reopenReminder(id))['completed'], false);
    await repository.deleteReminder(id);
    expect(
      (await repository.bootstrap()).reminders.any((r) => r.id == id),
      isFalse,
    );
    expect(() => repository.deleteReminder(id), throwsA(isA<PlusApiException>()));
  });

  test('demo estimate drafts can be edited, photos removed and drafts deleted', () async {
    final repository = DemoPlusRepository();
    final vehicle = (await repository.bootstrap()).vehicles.first;
    final draft = await repository.createEstimate({
      'vehicle_id': vehicle.id,
      'discipline': 'pdr',
      'description': 'Ding',
    });
    final id = draft['id'] as String;
    expect((await repository.updateEstimate(id, {'description': 'Two dings'}))['description'], 'Two dings');
    final photo = await repository.uploadPhoto(id, Uint8List.fromList([1, 2, 3]), 'a.jpg', 'front');
    await repository.deletePhoto(id, photo['id'] as String);
    final after = (await repository.bootstrap()).estimates.firstWhere((e) => e.id == id);
    expect(after.photos, isEmpty);
    await repository.deleteEstimate(id);
    expect((await repository.bootstrap()).estimates.any((e) => e.id == id), isFalse);
  });

  test('demo scheduling drafts can be discarded and sent requests withdrawn', () async {
    final repository = DemoPlusRepository();
    final shop = await repository.saveMyShop({'name': 'Shop', 'email': 'shop@example.test', 'phone': ''});
    final draft = await repository.createShopOutreach({
      'shop_id': shop['id'],
      'vehicle_id': (await repository.bootstrap()).vehicles.first.id,
      'service_summary': 'Brakes',
      'proposed_slots': [offsetTimestamp(DateTime.now().add(const Duration(days: 2)))],
    }, 'k1');
    await repository.deleteShopOutreach(draft['id'] as String);
    expect(await repository.listShopOutreach(), isEmpty);
    final second = await repository.createShopOutreach({
      'shop_id': shop['id'],
      'vehicle_id': (await repository.bootstrap()).vehicles.first.id,
      'service_summary': 'Brakes',
      'proposed_slots': [offsetTimestamp(DateTime.now().add(const Duration(days: 2)))],
    }, 'k2');
    await repository.authorizeShopOutreach(second['id'] as String, {'share_contact': true, 'review_hash': second['review_hash']}, 'a2');
    expect(() => repository.deleteShopOutreach(second['id'] as String), throwsA(isA<PlusApiException>()));
    expect((await repository.withdrawShopOutreach(second['id'] as String))['status'], 'withdrawn');
  });

  test('demo history records can be edited in place', () async {
    final repository = DemoPlusRepository();
    final vehicle = (await repository.bootstrap()).vehicles.first;
    final record = await repository.addKnowledgeRecord({
      'vehicle_id': vehicle.id,
      'service_type': 'maintenance',
      'service_date': '2026-09-01',
      'shop_name': 'Old',
    }, 'h1');
    final edited = await repository.updateKnowledgeRecord(record['id'] as String, {'shop_name': 'New', 'cost_cents': 500});
    expect(edited['shop_name'], 'New');
    expect(edited['cost_cents'], 500);
    expect(edited['service_date'], '2026-09-01');
  });

  test('demo valuation history is listed newest first and deletable', () async {
    final repository = DemoPlusRepository();
    final vehicle = (await repository.bootstrap()).vehicles.first;
    final before = (await repository.listVehicleValuations(vehicle.id))['valuations'] as List;
    expect(before, isNotEmpty); // seeded so the section is visible in the demo
    await repository.deleteVehicleValuation(vehicle.id, (before.first as Json)['id'] as String);
    final after = (await repository.listVehicleValuations(vehicle.id))['valuations'] as List;
    expect(after.length, before.length - 1);
  });
```

Add `import 'dart:typed_data';` and `import 'package:estimoto_plus/domain/models.dart';` at the top if missing; `offsetTimestamp` lives in `domain/models.dart` (check) and `Json` is the typedef there. Check the demo's `createShopOutreach` body keys by reading `demo_repository.dart:331-360` and `shop_outreach_screen.dart:195` and use the same keys.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd app && flutter test --no-pub test/repository_test.dart`
Expected: compile errors: `updateReminder` not defined.

- [ ] **Step 3: Extend the abstract repository**

In `repository.dart`, after `completeReminder`:

```dart
  Future<Json> updateReminder(String id, Json body) =>
      throw const PlusApiException('Reminders cannot be changed right now.');
  Future<void> deleteReminder(String id) =>
      throw const PlusApiException('Reminders cannot be changed right now.');
  Future<Json> reopenReminder(String id) =>
      throw const PlusApiException('Reminders cannot be changed right now.');
```

After `submitEstimate`:

```dart
  Future<Json> updateEstimate(String id, Json body) =>
      throw const PlusApiException('This estimate cannot be changed right now.');
  Future<void> deleteEstimate(String id) =>
      throw const PlusApiException('This estimate cannot be changed right now.');
  Future<void> deletePhoto(String estimateId, String photoId) =>
      throw const PlusApiException('This photo cannot be removed right now.');
```

After `authorizeShopOutreach`:

```dart
  Future<void> deleteShopOutreach(String id) =>
      throw const PlusApiException('This request cannot be discarded right now.');
  Future<Json> withdrawShopOutreach(String id) =>
      throw const PlusApiException('This request cannot be withdrawn right now.');
```

After `deleteKnowledgeRecord`:

```dart
  Future<Json> updateKnowledgeRecord(String id, Json body) =>
      throw const PlusApiException('History cannot be changed right now.');
```

After `lookupVehicleValue`:

```dart
  Future<Json> listVehicleValuations(String vehicleId) async =>
      {'vehicle_id': vehicleId, 'valuations': <Json>[]};
  Future<void> deleteVehicleValuation(String vehicleId, String valuationId) =>
      throw const PlusApiException('Past lookups cannot be removed right now.');
```

- [ ] **Step 4: Implement the live repository**

In `api_repository.dart` beside the siblings:

```dart
  @override
  Future<Json> updateReminder(String id, Json body) =>
      _send('PUT', '/v1/reminders/${Uri.encodeComponent(id)}', body: body);
  @override
  Future<void> deleteReminder(String id) async {
    await _send('DELETE', '/v1/reminders/${Uri.encodeComponent(id)}');
  }
  @override
  Future<Json> reopenReminder(String id) =>
      _send('POST', '/v1/reminders/${Uri.encodeComponent(id)}/reopen');

  @override
  Future<Json> updateEstimate(String id, Json body) =>
      _send('PUT', '/v1/estimates/${Uri.encodeComponent(id)}', body: body);
  @override
  Future<void> deleteEstimate(String id) async {
    await _send('DELETE', '/v1/estimates/${Uri.encodeComponent(id)}');
  }
  @override
  Future<void> deletePhoto(String estimateId, String photoId) async {
    await _send(
      'DELETE',
      '/v1/estimates/${Uri.encodeComponent(estimateId)}/photos/${Uri.encodeComponent(photoId)}',
    );
  }

  @override
  Future<void> deleteShopOutreach(String id) async {
    await _send('DELETE', '/v1/shop-outreach/${Uri.encodeComponent(id)}');
  }
  @override
  Future<Json> withdrawShopOutreach(String id) =>
      _send('POST', '/v1/shop-outreach/${Uri.encodeComponent(id)}/withdraw');

  @override
  Future<Json> updateKnowledgeRecord(String id, Json body) =>
      _send('PUT', '/v1/knowledge/records/${Uri.encodeComponent(id)}', body: body);

  @override
  Future<Json> listVehicleValuations(String vehicleId) =>
      _send('GET', '/v1/vehicles/${Uri.encodeComponent(vehicleId)}/valuations');
  @override
  Future<void> deleteVehicleValuation(String vehicleId, String valuationId) async {
    await _send(
      'DELETE',
      '/v1/vehicles/${Uri.encodeComponent(vehicleId)}/valuations/${Uri.encodeComponent(valuationId)}',
    );
  }
```

Read `_send` (`api_repository.dart:189+`) to confirm a 204 with empty body resolves to an empty map rather than throwing on JSON decode; `deleteKnowledgeRecord` already relies on that.

- [ ] **Step 5: Implement the demo repository**

Beside the siblings in `demo_repository.dart`:

```dart
  @override
  Future<Json> updateReminder(String id, Json body) async {
    final row = _find('reminders', id);
    final merged = {...row, ...body};
    if (merged['due_date'] == null && merged['due_mileage'] == null) {
      throw const PlusApiException('Add a date or mileage for this reminder.');
    }
    if (body['vehicle_id'] != null) _find('vehicles', body['vehicle_id'] as String);
    row.addAll(body);
    return row;
  }

  @override
  Future<void> deleteReminder(String id) async {
    _find('reminders', id);
    _rows('reminders').removeWhere((r) => r['id'] == id);
  }

  @override
  Future<Json> reopenReminder(String id) async {
    final row = _find('reminders', id);
    row['completed'] = false;
    return row;
  }

  Json _editableEstimate(String id) {
    final row = _find('estimates', id);
    if (row['status'] != 'draft' || (row['delivery_status'] ?? 'draft') != 'draft') {
      throw const PlusApiException(
        'This estimate has been shared and can no longer be changed.', 409, 'estimate_locked');
    }
    return row;
  }

  @override
  Future<Json> updateEstimate(String id, Json body) async {
    final row = _editableEstimate(id);
    row.addAll(body);
    row['updated_at'] = DateTime.now().toIso8601String();
    return row;
  }

  @override
  Future<void> deleteEstimate(String id) async {
    _editableEstimate(id);
    _rows('estimates').removeWhere((e) => e['id'] == id);
    _photoBytes.removeWhere((key, _) => key.startsWith('$id/'));
  }

  @override
  Future<void> deletePhoto(String estimateId, String photoId) async {
    final row = _editableEstimate(estimateId);
    final photos = row['photos'] as List;
    if (!photos.any((p) => p['id'] == photoId)) {
      throw const PlusApiException('Not found.', 404);
    }
    photos.removeWhere((p) => p['id'] == photoId);
    _photoBytes.remove('$estimateId/$photoId');
  }
```

Read the demo's `uploadPhoto`/`getPhoto` (`:539-562`) to learn the real name of the in-memory bytes map and the key format and use those instead of `_photoBytes` / `'$id/$photoId'`.

```dart
  @override
  Future<void> deleteShopOutreach(String id) async {
    final row = _workspaceFind(_outreach, id);
    if (!const {'draft', 'call_required', 'delivery_failed'}.contains(row['status'])) {
      throw const PlusApiException('This request was already sent and can only be withdrawn.', 409);
    }
    _outreach.removeWhere((r) => r['id'] == id);
  }

  @override
  Future<Json> withdrawShopOutreach(String id) async {
    final row = _workspaceFind(_outreach, id);
    if (!const {'queued', 'delivery_unknown', 'waiting_for_reply', 'local_preview'}.contains(row['status'])) {
      throw const PlusApiException('This request can no longer be withdrawn.', 409);
    }
    row['status'] = 'withdrawn';
    return _copy(row);
  }
```

Read `authorizeShopOutreach` in the demo (`:374-392`) for the status it assigns after authorizing an email shop (`local_preview` vs `queued`) and put that exact value in the withdrawable set so the repository test passes.

```dart
  @override
  Future<Json> updateKnowledgeRecord(String id, Json body) async {
    final row = _workspaceFind(_history, id);
    row.addAll(_copy(body));
    return _copy(row);
  }

  final Map<String, List<Json>> _valuations = {};

  @override
  Future<Json> listVehicleValuations(String vehicleId) async {
    _find('vehicles', vehicleId);
    return {'vehicle_id': vehicleId, 'valuations': (_valuations[vehicleId] ?? const []).map(_copy).toList()};
  }

  @override
  Future<void> deleteVehicleValuation(String vehicleId, String valuationId) async {
    final rows = _valuations[vehicleId] ?? [];
    if (!rows.any((r) => r['id'] == valuationId)) throw const PlusApiException('Not found.', 404);
    rows.removeWhere((r) => r['id'] == valuationId);
  }
```

Make `lookupVehicleValue` insert `{'id': _id(), 'state': ..., 'condition': ..., 'mileage': ..., 'created_at': ..., 'payload': <the same map it returns>}` at index 0 of `_valuations[vehicleId]` before returning. Seed two rows for the first demo vehicle in the constructor (where `_state` is built from `demo_seed.dart`) dated 30 and 90 days ago with retail/wholesale buckets 24,000 and 20,500 USD so the section shows.

Also override `openGuidedCapture` in the demo so it no longer hits the base throw:

```dart
  @override
  GuidedCaptureApi openGuidedCapture(String estimateId, {required bool Function() isCurrent}) =>
      throw const PlusApiException('The guided camera is unavailable in this preview.', 503, 'guided_capture_unavailable');
```

(The screen still short-circuits in demo; the typed code lets any future caller branch on it.)

In `plus_controller.dart` after `_notify`:

```dart
  void clearConversation() {
    messages.clear();
    _notify();
  }
```

- [ ] **Step 6: Run the tests and analyzer**

Run: `cd app && flutter analyze --no-pub && flutter test --no-pub test/repository_test.dart`
Expected: clean, all pass.

- [ ] **Step 7: Commit**

```bash
git add app/lib/data app/lib/state/plus_controller.dart app/test/repository_test.dart
git commit -m "Add repository operations for editing and deleting customer records"
```

---

### Task 8: Reminders: edit, delete, undo complete (UI)

**Files:**
- Modify: `app/lib/screens/garage_forms.dart:21-26` (`addReminder`), `:356-470` (`_ReminderForm`)
- Modify: `app/lib/screens/garage_screen.dart:180-222`
- Create: `app/test/reminder_flow_test.dart`

**Interfaces:**
- Consumes: `updateReminder`, `deleteReminder`, `reopenReminder` from Task 7.
- Produces: `Future<void> addReminder(BuildContext, PlusController, {Reminder? reminder})` (existing name, new optional parameter).

- [ ] **Step 1: Write the failing widget test**

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/app.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/state/plus_controller.dart';

Future<PlusController> _app(WidgetTester tester) async {
  final controller = PlusController(DemoPlusRepository());
  await controller.refresh();
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(EstimotoPlusApp(controller: controller, onExit: () {}));
  await tester.pumpAndSettle();
  return controller;
}

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('a reminder can be opened, edited and deleted from the garage', (tester) async {
    final controller = await _app(tester);
    final title = controller.snapshot!.reminders.first.title;
    await _tap(tester, find.text(title));
    expect(find.text('Edit reminder'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'What needs attention?'), 'Rotate tires');
    await _tap(tester, find.text('Save reminder'));
    expect(find.text('Rotate tires'), findsOneWidget);
    expect(find.text(title), findsNothing);
    await _tap(tester, find.text('Rotate tires'));
    await _tap(tester, find.text('Delete reminder'));
    expect(find.text('Delete this reminder?'), findsOneWidget);
    await _tap(tester, find.widgetWithText(TextButton, 'Delete'));
    expect(find.text('Rotate tires'), findsNothing);
    expect(controller.snapshot!.reminders.any((r) => r.title == 'Rotate tires'), isFalse);
  });

  testWidgets('completing a reminder offers undo', (tester) async {
    final controller = await _app(tester);
    final reminder = controller.snapshot!.reminders.first;
    await _tap(tester, find.byTooltip('Mark reminder complete').first);
    expect(find.text('Reminder completed'), findsOneWidget);
    expect(find.text(reminder.title), findsNothing);
    await _tap(tester, find.text('Undo'));
    expect(find.text(reminder.title), findsOneWidget);
    expect(controller.snapshot!.reminders.firstWhere((r) => r.id == reminder.id).completed, isFalse);
  });
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test --no-pub test/reminder_flow_test.dart`
Expected: FAIL: "Edit reminder" not found.

- [ ] **Step 3: Make the form edit-capable**

In `garage_forms.dart` change the opener and the form:

```dart
Future<void> addReminder(
  BuildContext context,
  PlusController controller, {
  Reminder? reminder,
}) => showModalBottomSheet<void>(
  context: context,
  isScrollControlled: true,
  builder: (_) => _ReminderForm(controller: controller, reminder: reminder),
);
```

```dart
class _ReminderForm extends StatefulWidget {
  const _ReminderForm({required this.controller, this.reminder});
  final PlusController controller;
  final Reminder? reminder;
  @override
  State<_ReminderForm> createState() => _ReminderFormState();
}
```

In `_ReminderFormState`: initialize from the reminder in `initState`:

```dart
  @override
  void initState() {
    super.initState();
    final r = widget.reminder;
    if (r != null) {
      title.text = r.title;
      if (r.dueMileage != null) mileage.text = r.dueMileage.toString();
      if (r.dueDate.isNotEmpty) date = DateTime.tryParse(r.dueDate);
    }
  }
```

Change `save()` so it calls `updateReminder` when editing:

```dart
      final body = {
        'vehicle_id': widget.reminder?.vehicleId ?? widget.controller.selectedVehicle!.id,
        'title': title.text.trim(),
        'due_date': date?.toIso8601String().substring(0, 10),
        'due_mileage': miles,
      };
      if (widget.reminder == null) {
        await widget.controller.repository.addReminder(body);
      } else {
        await widget.controller.repository.updateReminder(widget.reminder!.id, body);
      }
```

and skip the `selectedVehicle == null` guard when editing. Add a delete method:

```dart
  Future<void> remove() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this reminder?'),
        content: const Text('You can add it again any time.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => busy = true);
    try {
      await widget.controller.repository.deleteReminder(widget.reminder!.id);
      await widget.controller.refresh();
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) setState(() { error = PlusController.readableError(e); busy = false; });
    }
  }
```

In `build`: title `widget.reminder == null ? 'Add a reminder' : 'Edit reminder'`; hide `VehiclePicker` when editing; after the `BusyButton` add

```dart
        if (widget.reminder != null)
          Center(child: TextButton(onPressed: busy ? null : remove, child: const Text('Delete reminder'))),
```

- [ ] **Step 4: Wire the garage list**

In `garage_screen.dart` reminder `ListTile`, add `onTap: () => addReminder(context, controller, reminder: reminder),` and replace the complete action with an undo-capable snackbar:

```dart
                    trailing: IconButton(
                      tooltip: 'Mark reminder complete',
                      icon: const Icon(Icons.check_circle_outline),
                      onPressed: () async {
                        final messenger = ScaffoldMessenger.of(context);
                        try {
                          await controller.repository.completeReminder(reminder.id);
                          await controller.refresh();
                          messenger.showSnackBar(SnackBar(
                            content: const Text('Reminder completed'),
                            duration: const Duration(seconds: 6),
                            action: SnackBarAction(
                              label: 'Undo',
                              onPressed: () => runAction(context, controller, () async {
                                await controller.repository.reopenReminder(reminder.id);
                              }),
                            ),
                          ));
                        } catch (e) {
                          messenger.showSnackBar(SnackBar(content: Text(PlusController.readableError(e))));
                        }
                      },
                    ),
```

`GarageScreen` is a `StatelessWidget`; `context` inside the closure is the build context, which is fine because `messenger` is captured before the awaits and `runAction` checks `context.mounted`.

- [ ] **Step 5: Run tests and analyzer**

Run: `cd app && dart format lib/screens/garage_forms.dart lib/screens/garage_screen.dart test/reminder_flow_test.dart && flutter analyze --no-pub && flutter test --no-pub`
Expected: all pass (the existing garage/journey tests still find 'Add a reminder').

- [ ] **Step 6: Commit**

```bash
git add app/lib/screens/garage_forms.dart app/lib/screens/garage_screen.dart app/test/reminder_flow_test.dart
git commit -m "Edit, delete and undo-complete reminders from the garage"
```

---

### Task 9: Estimates: edit details, delete draft, delete photo, demo photo picker (UI)

**Files:**
- Modify: `app/lib/screens/estimate_forms.dart:78-110` (create form → reusable for edit), `:250-450` (`EstimateDetailScreen`)
- Modify: `app/lib/widgets/estimate_capture_guide.dart:495-549` (`EstimatePhotoGallery`)
- Create: `app/test/estimate_edit_test.dart`

**Interfaces:**
- Consumes: `updateEstimate`, `deleteEstimate`, `deletePhoto` (Task 7). `EstimatePhotoGallery` gains `final bool editable;` (default false) and `final Future<void> Function(String photoId)? onDelete;`.

- [ ] **Step 1: Write the failing widget test**

Use the harness from `app/test/estimate_flow_test.dart` (it opens the demo, starts an estimate and navigates to the detail screen; copy its `_open`/`_tap` helpers). Test:

```dart
  testWidgets('a draft can be edited, its photo removed, and deleted', (tester) async {
    final controller = await openDemoEstimateDetail(tester, description: 'Small dent');
    await _tap(tester, find.byTooltip('Estimate options'));
    await _tap(tester, find.text('Edit details'));
    await tester.enterText(find.widgetWithText(TextFormField, 'Describe the damage'), 'Small dent on the hood');
    await _tap(tester, find.text('Save changes'));
    expect(find.text('Small dent on the hood'), findsOneWidget);
    // Demo drafts can attach a photo through the simple picker.
    await _tap(tester, find.text('Choose photo'));
    await tester.pumpAndSettle();
    expect(find.text('Saved photos (1)'), findsOneWidget);
    await _tap(tester, find.byTooltip('Remove photo'));
    await _tap(tester, find.widgetWithText(TextButton, 'Remove'));
    expect(find.text('Saved photos (0)'), findsOneWidget);
    await _tap(tester, find.byTooltip('Estimate options'));
    await _tap(tester, find.text('Delete draft'));
    await _tap(tester, find.widgetWithText(TextButton, 'Delete'));
    expect(find.text('Your estimate'), findsNothing);
    expect(controller.snapshot!.estimates.any((e) => e.description == 'Small dent on the hood'), isFalse);
  });

  testWidgets('a shared estimate shows no edit or delete actions', (tester) async {
    final controller = await openDemoEstimateDetail(tester, description: 'Shared');
    // Force the demo row into the shared state the same way the backend does.
    final row = (controller.repository as DemoPlusRepository).debugEstimateRow(controller.snapshot!.estimates.first.id);
    row['delivery_status'] = 'queued';
    await controller.refresh();
    await tester.pumpAndSettle();
    await _tap(tester, find.byTooltip('Estimate options'));
    expect(find.text('Edit details'), findsNothing);
    expect(find.text('Delete draft'), findsNothing);
    expect(find.textContaining('can no longer be changed'), findsOneWidget);
  });
```

Add `Json debugEstimateRow(String id) => _find('estimates', id);` to `DemoPlusRepository` (annotated `@visibleForTesting`). The "Choose photo" step relies on the `EstimateCaptureService` test double already used by `estimate_flow_test.dart` (read how it injects `captureService`; pass the same fake that returns bytes).

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test --no-pub test/estimate_edit_test.dart`
Expected: FAIL: 'Estimate options' tooltip not found.

- [ ] **Step 3: Reuse the create form for editing**

In `estimate_forms.dart` the create form is the widget behind `newEstimate(...)` (line 78 region). Give it an optional `CustomerEstimate? estimate`; when present: prefill description, claim number and date; title "Edit estimate details"; button "Save changes"; on save call `controller.repository.updateEstimate(estimate.id, {...})` then `controller.refresh()` and `Navigator.pop`. Export `Future<void> editEstimate(BuildContext, PlusController, CustomerEstimate)` that opens it in a bottom sheet.

- [ ] **Step 4: Add the actions to the detail screen**

In `EstimateDetailScreen` build, define `final editable = estimate != null && estimate.status == 'draft' && textOf(estimate.json, 'delivery_status', 'draft') == 'draft';` (check the `CustomerEstimate` model in `domain/models.dart` for a `deliveryStatus` getter and use it if present). Add to the `AppBar.actions`:

```dart
                  if (estimate != null)
                    PopupMenuButton<String>(
                      tooltip: 'Estimate options',
                      itemBuilder: (_) => [
                        if (editable) const PopupMenuItem(value: 'edit', child: Text('Edit details')),
                        if (editable) const PopupMenuItem(value: 'delete', child: Text('Delete draft')),
                        if (!editable) const PopupMenuItem(enabled: false, value: 'locked',
                            child: Text('This estimate has been shared and can no longer be changed.')),
                      ],
                      onSelected: (value) => value == 'edit' ? editEstimate(context, widget.controller, estimate) : _delete(estimate),
                    ),
```

with

```dart
  Future<void> _delete(CustomerEstimate estimate) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this draft?'),
        content: const Text('Its saved photos are removed too. Nothing has been sent to a shop.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await runAction(context, widget.controller, () async {
      await widget.controller.repository.deleteEstimate(estimate.id);
    }, success: 'Draft deleted');
    if (mounted) Navigator.of(context).pop();
  }
```

Change the draft branch so the simple picker is reachable in demo: `recoveryOnly: !widget.controller.isDemo,` on the `EstimateCaptureGuide`. Read `EstimateCaptureGuide` to confirm that with `recoveryOnly: false` it renders "Take photo"/"Choose photo" buttons (the inventory says the buttons exist at `estimate_capture_guide.dart:141/179` paths); if their labels differ, use the real labels in the test.

Render the gallery in the draft branch too (currently only in the non-draft branch), passing `editable: editable` and `onDelete`:

```dart
                          EstimatePhotoGallery(
                            controller: widget.controller,
                            estimate: estimate,
                            editable: editable,
                            onDelete: (photoId) => runAction(context, widget.controller, () async {
                              await widget.controller.repository.deletePhoto(estimate.id, photoId);
                            }, success: 'Photo removed'),
                          ),
```

- [ ] **Step 5: Add delete to the gallery tiles**

In `EstimatePhotoGallery` add the two fields and, inside each tile's `Column` after the label:

```dart
                    if (editable && onDelete != null)
                      IconButton(
                        tooltip: 'Remove photo',
                        visualDensity: VisualDensity.compact,
                        icon: const Icon(Icons.delete_outline, size: 20),
                        onPressed: () async {
                          final confirmed = await showDialog<bool>(
                            context: context,
                            builder: (context) => AlertDialog(
                              title: const Text('Remove this photo?'),
                              content: const Text('You can take it again from the guided photos.'),
                              actions: [
                                TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
                                TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Remove')),
                              ],
                            ),
                          );
                          if (confirmed == true) await onDelete!(textOf(photo, 'id'));
                        },
                      ),
```

- [ ] **Step 6: Run tests and analyzer**

Run: `cd app && dart format lib/screens/estimate_forms.dart lib/widgets/estimate_capture_guide.dart lib/data/demo_repository.dart test/estimate_edit_test.dart && flutter analyze --no-pub && flutter test --no-pub`
Expected: all pass. If `estimate_flow_test.dart` asserted that the draft screen has no gallery or no picker in demo, update that assertion to the new behaviour in the same commit and say so in the commit body.

- [ ] **Step 7: Commit**

```bash
git add app/lib app/test
git commit -m "Edit, delete and remove photos from unshared estimate drafts"
```

---

### Task 10: Scheduling requests: discard, withdraw, discard interrupted draft (UI)

**Files:**
- Modify: `app/lib/screens/my_shops_screen.dart:168-190`, `:284-330`
- Modify: `app/lib/screens/shop_outreach_screen.dart:676-724` (review actions)
- Modify: `app/lib/services/customer_workspace.dart` (add `discardPending(String operation)`)
- Modify: `app/test/customer_workspace_ui_test.dart` (append)

**Interfaces:**
- Consumes: `deleteShopOutreach`, `withdrawShopOutreach` (Task 7).
- Produces: `Future<void> CustomerWorkspace.discardPending(String operation)` which clears the store scope.

- [ ] **Step 1: Write the failing tests**

Append to `customer_workspace_ui_test.dart`, reusing its `_Repository`, `_controller`, `_mount`, `_tap`:

```dart
  testWidgets('a draft scheduling request can be discarded from my shops', (tester) async {
    final controller = await _controller();
    final shop = await controller.repository.saveMyShop({'name': 'Shop', 'email': 's@example.test', 'phone': ''});
    await controller.repository.createShopOutreach({
      'shop_id': shop['id'],
      'vehicle_id': controller.snapshot!.vehicles.first.id,
      'service_summary': 'Brakes',
      'proposed_slots': [offsetTimestamp(DateTime.now().add(const Duration(days: 2)))],
    }, 'draft-key');
    await _mount(tester, MyShopsScreen(controller: controller));
    expect(find.text('Draft • not sent'), findsOneWidget);
    await _tap(tester, find.byTooltip('Request options').first);
    await _tap(tester, find.text('Discard request'));
    expect(find.text('Discard this request?'), findsOneWidget);
    await _tap(tester, find.widgetWithText(TextButton, 'Discard'));
    expect(find.text('Draft • not sent'), findsNothing);
    expect(await controller.repository.listShopOutreach(), isEmpty);
  });

  testWidgets('a sent request can be withdrawn from its review screen', (tester) async {
    final repository = _Repository();
    final controller = await _controller(repository);
    repository.draft = {...repository.draft, 'status': 'waiting_for_reply', 'delivery_status': 'provider_accepted'};
    await _mount(tester, ShopOutreachReview(controller: controller, outreachId: 'draft-1'));
    await _tap(tester, find.text('Withdraw request'));
    expect(find.text('Withdraw this request?'), findsOneWidget);
    await _tap(tester, find.widgetWithText(TextButton, 'Withdraw'));
    expect(find.text('Withdrawn'), findsOneWidget);
  });

  testWidgets('an interrupted device draft can be discarded', (tester) async {
    final controller = await _controller();
    final workspace = CustomerWorkspace(controller: controller, store: MemoryWorkspaceWriteStore());
    await workspace.store.write(workspace.scopeFor('outreach-draft'), PendingWorkspaceWrite(body: const {'x': 1}, key: 'k'));
    await _mount(tester, MyShopsScreen(controller: controller, workspace: workspace));
    expect(find.text('Recover scheduling draft'), findsOneWidget);
    await _tap(tester, find.text('Discard draft'));
    await _tap(tester, find.widgetWithText(TextButton, 'Discard'));
    expect(find.text('Recover scheduling draft'), findsNothing);
  });
```

Read `CustomerWorkspace` (`customer_workspace.dart:77-100`) for its constructor, how `MyShopsScreen` obtains a workspace (constructor parameter or created internally), the `_scope` helper name (expose it as `String scopeFor(String operation)` if private), and `PendingWorkspaceWrite`'s constructor. In `_Repository`, `withdrawShopOutreach` must be overridden to flip `draft['status']` to `'withdrawn'` and return it, and `outreachStatusLabel` must map `'withdrawn'` → `'Withdrawn'` (find it via grep in `app/lib`).

- [ ] **Step 2: Run to verify they fail**

Run: `cd app && flutter test --no-pub test/customer_workspace_ui_test.dart`
Expected: FAIL: 'Request options' not found.

- [ ] **Step 3: Add `discardPending` to the workspace**

```dart
  Future<void> discardPending(String operation) async {
    check();
    await store.clear(_scope(operation));
  }
  String scopeFor(String operation) => _scope(operation);
```

- [ ] **Step 4: My shops cards and interrupted draft**

In the interrupted-draft block add beside "Recover scheduling draft":

```dart
            TextButton(
              onPressed: busy ? null : () async {
                final confirmed = await showDialog<bool>(
                  context: context,
                  builder: (context) => AlertDialog(
                    title: const Text('Discard the saved draft?'),
                    content: const Text('Its details are removed from this device. Nothing was sent to the shop.'),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
                      TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Discard')),
                    ],
                  ),
                );
                if (confirmed != true || !active) return;
                await perform(() async {
                  await workspace.discardPending('outreach-draft');
                  if (active) await load();
                });
              },
              child: const Text('Discard draft'),
            ),
```

In each request card, add a trailing `PopupMenuButton<String>(tooltip: 'Request options', ...)` in the title `Row` whose items depend on status:

```dart
  static const _discardable = {'draft', 'call_required', 'delivery_failed'};
  static const _withdrawable = {'queued', 'delivery_unknown', 'waiting_for_reply', 'local_preview'};

  Future<void> discard(Json draft) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Discard this request?'),
        content: const Text('It was never sent. You can prepare a new one any time.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Discard')),
        ],
      ),
    );
    if (confirmed != true || !active) return;
    await perform(() async {
      await controller.repository.deleteShopOutreach(draft['id'] as String);
      if (active) await load();
    });
  }

  Future<void> withdraw(Json draft) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Withdraw this request?'),
        content: const Text('The shop’s confirmation link stops working. No message is sent to the shop, so call them if a time was already discussed.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Withdraw')),
        ],
      ),
    );
    if (confirmed != true || !active) return;
    await perform(() async {
      await controller.repository.withdrawShopOutreach(draft['id'] as String);
      if (active) await load();
    });
  }
```

Menu items: `'Discard request'` when `_discardable.contains(status)`, `'Withdraw request'` when `_withdrawable.contains(status)`; no menu for `confirmed`/`withdrawn`.

- [ ] **Step 5: Review screen actions**

In `ShopOutreachReview` after the `call_required` button add the same two actions as `OutlinedButton`s gated by the same status sets, using identical dialogs (extract both dialogs into `app/lib/widgets/outreach_actions.dart` as `Future<bool> confirmDiscard(BuildContext)` and `Future<bool> confirmWithdraw(BuildContext)` so the copy lives once). After withdrawal, `load()` re-reads the outreach and the status pill shows "Withdrawn" via `outreachStatusLabel`.

- [ ] **Step 6: Run tests and analyzer**

Run: `cd app && dart format lib/screens/my_shops_screen.dart lib/screens/shop_outreach_screen.dart lib/services/customer_workspace.dart lib/widgets/outreach_actions.dart test/customer_workspace_ui_test.dart && flutter analyze --no-pub && flutter test --no-pub`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/lib app/test
git commit -m "Discard drafts, withdraw sent requests and clear interrupted scheduling drafts"
```

---

### Task 11: Service history: edit in place (UI)

**Files:**
- Modify: `app/lib/screens/history_screen.dart:258-300` (cards), `:374-500` (`HistoryEditor`)
- Modify: `app/lib/services/customer_workspace.dart:171` (add `updateHistory`)
- Modify: `app/test/customer_workspace_ui_test.dart` (append)

**Interfaces:**
- Consumes: `updateKnowledgeRecord` (Task 7).
- Produces: `HistoryEditor({..., Json? record})`; `Future<Json> CustomerWorkspace.updateHistory(String id, Json body)` (direct call, no idempotency store: an update is naturally idempotent).

- [ ] **Step 1: Write the failing test**

```dart
  testWidgets('a history record can be edited and keeps its receipts', (tester) async {
    final controller = await _controller();
    final record = await controller.repository.addKnowledgeRecord({
      'vehicle_id': controller.snapshot!.vehicles.first.id,
      'service_type': 'maintenance',
      'service_date': '2026-09-01',
      'shop_name': 'Old Shop',
      'cost_cents': 1000,
    }, 'h-edit');
    (record['receipts'] as List).add({'id': 'r1', 'filename': 'a.pdf', 'content_type': 'application/pdf', 'byte_size': 10});
    await _mount(tester, HistoryScreen(controller: controller));
    await _tap(tester, find.byTooltip('Edit history entry').first);
    expect(find.text('Edit service history'), findsOneWidget);
    expect(find.textContaining('1 receipt stays attached'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextFormField, 'Shop or DIY (optional)'), 'New Shop');
    await _tap(tester, find.text('Save changes'));
    expect(find.text('New Shop'), findsOneWidget);
    expect(find.text('Old Shop'), findsNothing);
  });
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test --no-pub test/customer_workspace_ui_test.dart -n "history record can be edited"`
Expected: FAIL: 'Edit history entry' not found.

- [ ] **Step 3: Workspace helper**

```dart
  Future<Json> updateHistory(String id, Json body) async {
    check();
    final result = await controller.repository.updateKnowledgeRecord(id, body);
    check();
    return result;
  }
```

- [ ] **Step 4: Editor accepts a record**

Add `this.record` (`final Json? record;`) to `HistoryEditor`. In `_HistoryEditorState.initState` (find where `fields` are populated) prefill from `widget.record`: `vehicleId`, `type = textOf(record,'service_type')`, `date = DateTime.parse(textOf(record,'service_date'))`, each text field from the record (`mileage` → `intOf(record,'mileage')?.toString()`, `cost_cents` → dollars string via the inverse of `parseReceiptCost`; check `history_receipts_screen.dart` for a `costText`/`moneyText` helper and use it). In `save()`, when `widget.record != null` and `pending == null`, call `workspace.updateHistory(widget.record!['id'] as String, body)` instead of `addHistory`, then `controller.historyChanged()`, then `Navigator.pop(context)`. Title `'Edit service history'` vs the existing title; button `'Save changes'`; when editing and `rowsOf(widget.record!, 'receipts')` is not empty, show `Text('${n} receipt${n == 1 ? '' : 's'} stays attached to this entry.')` above the button.

- [ ] **Step 5: Card action**

Next to the existing delete `IconButton` in the card header add:

```dart
                          IconButton(
                            tooltip: 'Edit history entry',
                            onPressed: busy ? null : () => openEditor(record),
                            icon: const Icon(Icons.edit_outlined),
                          ),
```

where `openEditor` pushes `HistoryEditor(controller: controller, record: record, receiptStore: ..., captureService: ..., pdfPicker: ...)` the same way the "Add service history" button does (read `history_screen.dart:178-192`), then `await load()` on return.

- [ ] **Step 6: Run tests and analyzer**

Run: `cd app && dart format lib/screens/history_screen.dart lib/services/customer_workspace.dart test/customer_workspace_ui_test.dart && flutter analyze --no-pub && flutter test --no-pub`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/lib app/test
git commit -m "Edit service history entries in place"
```

---

### Task 12: Vehicle value: history list on open (UI)

**Files:**
- Modify: `app/lib/screens/vehicle_value_screen.dart:95-160` and its `build`
- Modify: `app/test/vehicle_value_test.dart` (append)

**Interfaces:**
- Consumes: `listVehicleValuations`, `deleteVehicleValuation` (Task 7).

- [ ] **Step 1: Write the failing test**

Read `vehicle_value_test.dart` for its harness (`_Repository extends DemoPlusRepository`, how it mounts `VehicleValueScreen`). Append:

```dart
  testWidgets('past lookups load on open, the latest shows first, and rows can be removed', (tester) async {
    final repository = DemoPlusRepository();
    final controller = PlusController(repository);
    await controller.refresh();
    final vehicle = controller.snapshot!.vehicles.first;
    await mountValueScreen(tester, controller, vehicle.id);
    expect(find.text('Past lookups'), findsOneWidget);
    final seeded = (await repository.listVehicleValuations(vehicle.id))['valuations'] as List;
    expect(find.byTooltip('Remove past lookup'), findsNWidgets(seeded.length));
    expect(find.textContaining('Latest'), findsOneWidget);
    await tester.tap(find.byTooltip('Remove past lookup').first);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Remove'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Remove past lookup'), findsNWidgets(seeded.length - 1));
  });
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test --no-pub test/vehicle_value_test.dart`
Expected: FAIL: 'Past lookups' not found.

- [ ] **Step 3: Load history on open and after lookups**

In `_VehicleValueScreenState` add `List<Json> history = [];` and

```dart
  Future<void> loadHistory() async {
    if (!current) return;
    try {
      final data = await controller.repository.listVehicleValuations(id);
      if (!current) return;
      setState(() => history = rowsOf(data, 'valuations'));
    } catch (e) {
      if (current) setState(() => error = PlusController.readableError(e));
    }
  }

  Future<void> removeHistory(Json row) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remove this past lookup?'),
        content: const Text('Only your saved copy is removed.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Remove')),
        ],
      ),
    );
    if (confirmed != true || !current) return;
    try {
      await controller.repository.deleteVehicleValuation(id, row['id'] as String);
      await loadHistory();
    } catch (e) {
      if (current) setState(() => error = PlusController.readableError(e));
    }
  }
```

Call `loadHistory()` from `initState` (after the existing setup) and at the end of a successful `lookup()`. In `build`, after the current result block, render:

```dart
          const SectionHeading('Past lookups'),
          if (history.isEmpty)
            const Text('Lookups you run are kept here for this vehicle.')
          else
            for (final (index, row) in history.indexed)
              Card(
                child: ListTile(
                  title: Text('${index == 0 ? 'Latest · ' : ''}${dateText(textOf(row, 'created_at').substring(0, 10))}'),
                  subtitle: Text('${textOf(row, 'state')} · ${textOf(row, 'condition')} · ${mileageText(intOf(row, 'mileage'))} miles · '
                      '${bucketSummary(row['payload'] as Json)}'),
                  trailing: IconButton(
                    tooltip: 'Remove past lookup',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: busy ? null : () => removeHistory(row),
                  ),
                ),
              ),
```

with `String bucketSummary(Json payload)` returning e.g. `Retail $24,000 · Wholesale $20,500` by reading `rowsOf(payload, 'buckets')` the same way the current result block formats `buckets` (copy that formatting). When `result == null && history.isNotEmpty`, show the latest row's `payload` through the existing result renderer so the last value is visible on open.

- [ ] **Step 4: Run tests and analyzer**

Run: `cd app && dart format lib/screens/vehicle_value_screen.dart test/vehicle_value_test.dart && flutter analyze --no-pub && flutter test --no-pub`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/lib/screens/vehicle_value_screen.dart app/test/vehicle_value_test.dart
git commit -m "Show and manage past vehicle value lookups"
```

---

### Task 13: Estibot clear and unmatched chip, demo calendar disconnect, device time zone

**Files:**
- Modify: `app/lib/screens/estibot_screen.dart:22-60` and the message list around `:158`
- Modify: `app/lib/data/demo_repository.dart:780` (unmatched reply) and `app/lib/domain/models.dart:303-315` (`AssistantAnswer.intent` if missing)
- Modify: `app/lib/screens/calendar_screen.dart:465`
- Create: `app/lib/services/time_zone.dart`, `app/lib/services/time_zone_web.dart`, `app/lib/services/time_zone_native.dart`
- Modify: `app/lib/screens/calendar_screen.dart:42,89` and `app/lib/widgets/calendar_slot_picker.dart` where `'Etc/UTC'` is the fallback
- Create: `app/test/estibot_actions_test.dart`, `app/test/time_zone_test.dart`; modify `app/test/calendar_flow_test.dart`

- [ ] **Step 1: Write the failing tests**

`estibot_actions_test.dart` (harness copied from `settings_test.dart`, mounting the full app and tapping the Estibot tab):

```dart
  testWidgets('the conversation can be cleared', (tester) async {
    final controller = await _app(tester);
    await _tap(tester, find.byKey(const Key('nav-estibot')));
    await _tap(tester, find.text('How do I check tire pressure?'));
    expect(controller.messages, isNotEmpty);
    await _tap(tester, find.byTooltip('Conversation options'));
    await _tap(tester, find.text('Clear conversation'));
    await _tap(tester, find.widgetWithText(TextButton, 'Clear'));
    expect(controller.messages, isEmpty);
    expect(find.text('How do I check tire pressure?'), findsOneWidget); // the prompt chip is back
  });

  testWidgets('an unmatched question offers the technician search', (tester) async {
    final controller = await _app(tester);
    await _tap(tester, find.byKey(const Key('nav-estibot')));
    await tester.enterText(find.widgetWithText(TextField, 'Ask about your car…'), 'my check engine light is on');
    await _tap(tester, find.byTooltip('Send message'));
    expect(find.textContaining("I can't answer that one yet"), findsOneWidget);
    expect(find.text('Find a technician for this'), findsOneWidget);
    await _tap(tester, find.text('Find a technician for this'));
    expect(controller.tab, 4);
  });
```

Read `customer_navigation.dart` for the Estibot nav key (`nav-estibot` or similar) and `estibot_screen.dart` for the send button tooltip.

`time_zone_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/services/time_zone.dart';

void main() {
  test('US abbreviations map to IANA zones and unknown ones do not', () {
    expect(ianaFromAbbreviation('MDT'), 'America/Denver');
    expect(ianaFromAbbreviation('MST'), 'America/Denver');
    expect(ianaFromAbbreviation('PST'), 'America/Los_Angeles');
    expect(ianaFromAbbreviation('EDT'), 'America/New_York');
    expect(ianaFromAbbreviation('CST'), 'America/Chicago');
    expect(ianaFromAbbreviation('AKDT'), 'America/Anchorage');
    expect(ianaFromAbbreviation('HST'), 'Pacific/Honolulu');
    expect(ianaFromAbbreviation('CEST'), isNull);
    expect(ianaFromAbbreviation(''), isNull);
  });
  test('the fallback is only used when no preference is saved', () {
    expect(effectiveTimeZone(saved: 'America/Chicago', device: 'America/Denver'), 'America/Chicago');
    expect(effectiveTimeZone(saved: 'Etc/UTC', device: 'America/Denver'), 'America/Denver');
    expect(effectiveTimeZone(saved: '', device: null), 'Etc/UTC');
  });
}
```

In `calendar_flow_test.dart` add one case asserting the Calendar screen's time-zone field shows `America/Denver` when `deviceTimeZoneOverride = 'America/Denver'` (a test hook on the service, see Step 4) and the repository status returns `'Etc/UTC'`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd app && flutter test --no-pub test/estibot_actions_test.dart test/time_zone_test.dart`
Expected: FAIL (import errors / tooltip missing).

- [ ] **Step 3: Estibot**

Wrap the Estibot screen body in a `Column` whose first row holds a `PopupMenuButton<String>(tooltip: 'Conversation options', ...)` with `Clear conversation` (visible only when `controller.messages.isNotEmpty`), confirmed by an `AlertDialog` "Clear this conversation?" with `Keep`/`Clear`, calling `widget.controller.clearConversation()`. In the message list, when an assistant entry's answer has `intent == 'unmatched'`, render `ActionChip(label: const Text('Find a technician for this'), onPressed: () => widget.controller.selectTab(4))` under it. Read `ChatEntry` in `plus_controller.dart` for where the `AssistantAnswer` is stored on an entry; add `String get intent => textOf(json, 'intent');` to `AssistantAnswer` if it lacks one. In the demo repository change the fallback reply at `:780` to `"I can't answer that one yet. I can explain an estimate, plan routine maintenance, or find a technician near you."` with `'intent': 'unmatched'`.

- [ ] **Step 4: Time zone service**

`time_zone.dart`:

```dart
import 'time_zone_native.dart' if (dart.library.js_interop) 'time_zone_web.dart' as platform;

const _usZones = {
  'EST': 'America/New_York', 'EDT': 'America/New_York',
  'CST': 'America/Chicago', 'CDT': 'America/Chicago',
  'MST': 'America/Denver', 'MDT': 'America/Denver',
  'PST': 'America/Los_Angeles', 'PDT': 'America/Los_Angeles',
  'AKST': 'America/Anchorage', 'AKDT': 'America/Anchorage',
  'HST': 'Pacific/Honolulu',
};

String? ianaFromAbbreviation(String abbreviation) => _usZones[abbreviation.toUpperCase()];

/// Test hook; production leaves it null.
String? deviceTimeZoneOverride;

String? deviceTimeZone() => deviceTimeZoneOverride ?? platform.deviceTimeZone();

String effectiveTimeZone({required String saved, required String? device}) {
  if (saved.isNotEmpty && saved != 'Etc/UTC') return saved;
  return device ?? 'Etc/UTC';
}
```

`time_zone_native.dart`:

```dart
import 'time_zone.dart';

String? deviceTimeZone() => ianaFromAbbreviation(DateTime.now().timeZoneName);
```

`time_zone_web.dart` (use `dart:js_interop` the way the existing `*_web.dart` services in `app/lib/services` do):

```dart
import 'dart:js_interop';

@JS('Intl.DateTimeFormat')
external JSFunction get _dateTimeFormat;

String? deviceTimeZone() {
  try {
    final options = (_dateTimeFormat.callAsConstructor() as JSObject)
        .callMethod('resolvedOptions'.toJS) as JSObject;
    final zone = options.getProperty('timeZone'.toJS);
    final text = (zone as JSString?)?.toDart;
    return (text == null || text.isEmpty) ? null : text;
  } catch (_) {
    return null;
  }
}
```

Adjust to the interop style already used in `guided_capture_pending_web.dart` if that file uses `package:web` instead. Then in `calendar_screen.dart:42` initialise `zone` with `effectiveTimeZone(saved: '', device: deviceTimeZone())`, and at `:89` use `effectiveTimeZone(saved: textOf(value, 'time_zone', ''), device: deviceTimeZone())`; do the same where `calendar_slot_picker.dart`, `request_sheet.dart:323` and `shop_outreach_screen.dart:368` fall back to `'Etc/UTC'`. A saved non-UTC preference always wins.

- [ ] **Step 5: Demo calendar disconnect**

In `calendar_screen.dart:465` drop the `!controller.isDemo &&` guard. Read the demo `disconnectGoogleCalendar` (`demo_repository.dart:215`) and make sure it flips its seeded status to `connected: false, status: 'not_connected'` so the screen re-renders the not-connected state; extend an existing calendar demo test to tap `calendar-disconnect` and expect `find.text('Disconnect Google Calendar'), findsNothing` afterwards.

- [ ] **Step 6: Run tests and analyzer**

Run: `cd app && dart format lib test && flutter analyze --no-pub && flutter test --no-pub`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/lib app/test
git commit -m "Clear Estibot conversations, offer technician search on unmatched questions, use device time zone, allow demo calendar disconnect"
```

---

### Task 14: Smoke, docs and final verification

**Files:**
- Modify: `scripts/smoke_api.py` (after the reminder/estimate section)
- Modify: `docs/api-contract.md`, `docs/release-status.md`, `README.md`, create `docs/releases/0.1.0-11-beta-notes.md`
- Modify: `app/pubspec.yaml` version → `0.1.0+11`, `app/lib/build_info.dart` default `'11'`

- [ ] **Step 1: Extend the socket smoke**

In `scripts/smoke_api.py`, read how it creates a reminder and an estimate over the socket, then after those calls add:

```python
    reminder = post('/v1/reminders', {'vehicle_id': vehicle_id, 'title': 'Smoke', 'due_mileage': 100})
    assert put(f"/v1/reminders/{reminder['id']}", {'title': 'Smoke edited'})['title'] == 'Smoke edited'
    assert delete(f"/v1/reminders/{reminder['id']}") == 204
    draft = post('/v1/estimates', {'vehicle_id': vehicle_id, 'discipline': 'pdr', 'description': 'smoke'})
    assert put(f"/v1/estimates/{draft['id']}", {'description': 'smoke edited'})['description'] == 'smoke edited'
    assert delete(f"/v1/estimates/{draft['id']}") == 204
```

using the script's own request helpers (add `put`/`delete` helpers mirroring `post` if absent). Run `backend/.venv/bin/python scripts/smoke_api.py` from the repo root; expected: the final "passed" line.

- [ ] **Step 2: Docs**

Add every new route to `docs/api-contract.md` in the entity sections, with one line each (method, path, body, response, 404/409 rules). Add to `docs/release-status.md` "Implemented customer workflows" the sentence: "Reminders, estimate drafts and their photos, scheduling requests, service history and valuation lookups can be edited, withdrawn or deleted from the app; shared estimates and confirmed appointments stay locked." Create `docs/releases/0.1.0-11-beta-notes.md` listing the new actions in customer words. Bump `app/pubspec.yaml` to `0.1.0+11` and `build_info.dart` default to `'11'`.

- [ ] **Step 3: Full verification**

```bash
cd backend && .venv/bin/python -m pytest -q && cd ..
cd app && flutter analyze --no-pub && flutter test --no-pub && flutter build web --no-pub --dart-define=PLUS_DEMO=true && cd ..
backend/.venv/bin/python scripts/smoke_api.py
backend/.venv/bin/python scripts/smoke_discovery.py
backend/.venv/bin/python scripts/smoke_calendar.py
DATABASE_URL=sqlite:///$(mktemp -u).db backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
```

Expected: every suite green, web build succeeds, smokes print passed, migration upgrades to `b7f2c9d4e1a0`.

- [ ] **Step 4: Browser walk**

Serve `app/build/web` on 127.0.0.1:4318 and, using the Playwright driver in the session scratchpad (`pw/drive.js`), walk: Garage reminder tap → edit → delete; Estimates → draft → options → edit → delete; My shops → draft → discard; History → edit; Vehicle value → past lookups; Estibot → clear. Screenshot each. Fix anything that does not match the tests' expectations before the final commit.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Extend smokes and docs for build 11 CRUD closure"
```

Then hand back to the user: merge `origin/main` into the branch, re-run both suites, fast-forward `main`, push, and ask for the deploy (the deploy command needs the user's permission in this environment).
