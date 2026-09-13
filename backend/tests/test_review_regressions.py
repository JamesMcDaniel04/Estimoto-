import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from estimoto_plus import bridge as bridge_module
from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.models import Outbox, ServiceRequest, now

AUTH = {"Authorization": "Bearer alice"}
BRIDGE = {"X-Bridge-Key": "secret"}


@pytest.fixture
def make(tmp_path):
    clients = []
    def create(name, transport=None, postal="80202"):
        settings = Settings(database_url=f"sqlite:///{tmp_path / name}.sqlite", environment="test",
                            bridge_url="https://fixture.invalid/requests", bridge_key="secret", photo_dir=str(tmp_path / name / "photos"))
        verifier = lambda token: {"id": token, "email": f"{token}@example.test", "email_confirmed_at": "ok"}
        app = create_app(settings, auth_verifier=verifier, bridge_transport=httpx.MockTransport(transport or (lambda _: httpx.Response(202, json={"receipt_id": "receipt"}))))
        client = TestClient(app, raise_server_exceptions=False)
        clients.append(client)
        vehicle = client.post("/v1/vehicles", headers=AUTH, json={"year": 2020, "make": "Ford", "model": "Truck"}).json()["id"]
        if postal is not None:
            result = client.put("/v1/profile", headers=AUTH, json={"postal_code": postal})
            assert result.status_code == (422 if postal == "not-a-zip" else 200)
        provider = client.post("/v1/bridge/providers", headers=BRIDGE, json={"source_id": "shop-1", "name": "Shop", "kind": "shop", "specialties": ["pdr"], "postal_codes": ["80202"], "public_visible": True, "accepting_requests": True}).json()["id"]
        body = {"vehicle_id": vehicle, "provider_id": provider, "specialty": "pdr", "description": "Dent", "share_contact": True}
        return app, client, vehicle, provider, body
    yield create
    for client in clients:
        client.close()


def create_request(client, body, key="key"):
    return client.post("/v1/requests", headers={**AUTH, "Idempotency-Key": key}, json=body)


def deliver(client):
    return client.post("/v1/bridge/outbox/deliver", headers=BRIDGE)


def request_state(client):
    return client.get("/v1/requests", headers=AUTH).json()[0]


def test_missing_or_invalid_saved_zip_cannot_create_request(make):
    for postal in (None, "", "   ", "not-a-zip"):
        _, client, _, _, body = make(f"zip-{postal!r}", postal=postal)
        assert create_request(client, body).status_code in {409, 422}
        assert client.get("/v1/requests", headers=AUTH).json() == []


def test_valid_zip_is_normalized_and_provider_area_is_exact(make):
    app, client, _, _, body = make("valid-zip", postal=" 80202 ")
    assert client.get("/v1/bootstrap", headers=AUTH).json()["profile"]["postal_code"] == "80202"
    assert create_request(client, body).status_code == 201
    assert deliver(client).json()["delivered"] == 1


def test_repair_stages_with_null_and_date_persist_and_replay(make):
    _, client, vehicle, _, _ = make("repairs")
    body = {"source_id": "repair-1", "customer_id": "alice", "vehicle_id": vehicle, "provider_name": "Shop", "title": "Repair", "status": "working",
            "stages": [{"title": "Inspection", "status": "completed", "date": "2026-09-13"}, {"title": "Repair", "status": "current", "date": None}]}
    first = client.post("/v1/bridge/repairs/snapshots", headers=BRIDGE, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["stages"] == body["stages"]
    second = client.post("/v1/bridge/repairs/snapshots", headers=BRIDGE, json={**body, "status": "finishing"})
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert client.get("/v1/bootstrap", headers={"Authorization": "Bearer bob"}).json()["repairs"] == []
    assert client.post("/v1/bridge/repairs/snapshots", headers=BRIDGE, json={**body, "customer_id": "bob"}).status_code in {404, 409}


def test_cancel_during_inflight_create_eventually_sends_tombstone(make):
    entered, release = threading.Event(), threading.Event()
    sent = []
    def transport(req):
        sent.append(json.loads(req.content))
        if len(sent) == 1:
            entered.set()
            assert release.wait(5)
        return httpx.Response(202, json={"receipt_id": f"receipt-{len(sent)}"})
    app, client, _, _, body = make("cancel-race", transport)
    rid = create_request(client, body).json()["id"]
    with ThreadPoolExecutor() as pool:
        worker = pool.submit(deliver, client)
        assert entered.wait(5)
        assert client.post(f"/v1/requests/{rid}/cancel", headers=AUTH).status_code == 200
        release.set()
        assert worker.result().status_code == 200
    assert request_state(client)["status"] == "cancelled"
    assert deliver(client).json()["delivered"] == 1
    assert [item["event"] for item in sent] == ["created", "cancelled"]
    with app.state.session_factory() as db:
        rows = db.query(Outbox).filter(Outbox.request_id == rid).all()
        assert {row.kind: row.receipt_id for row in rows} == {"create": "receipt-1", "cancel": "receipt-2"}


def test_cancel_after_ambiguous_timeout_reconciles_create_then_cancels(make):
    sent = []
    def transport(req):
        sent.append(json.loads(req.content))
        if len(sent) == 1:
            raise httpx.ReadTimeout("upstream may have accepted", request=req)
        return httpx.Response(202, json={"receipt_id": f"receipt-{len(sent)}"})
    app, client, _, _, body = make("cancel-timeout", transport)
    rid = create_request(client, body).json()["id"]
    assert deliver(client).json() == {"delivered": 0, "failed": 1}
    assert client.post(f"/v1/requests/{rid}/cancel", headers=AUTH).status_code == 200
    assert deliver(client).json()["delivered"] == 1
    assert deliver(client).json()["delivered"] == 0
    assert [item["event"] for item in sent] == ["created", "cancelled"]
    assert request_state(client)["status"] == "cancelled"
    with app.state.session_factory() as db:
        create_row = db.query(Outbox).filter(Outbox.request_id == rid, Outbox.kind == "create").one()
        assert create_row.suppressed is True


def test_overlapping_workers_claim_once_and_late_failure_cannot_erase_receipt(make):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def transport(req):
        calls.append(req)
        entered.set()
        assert release.wait(5)
        return httpx.Response(202, json={"receipt_id": "receipt"})
    app, client, _, _, body = make("worker-claim", transport)
    rid = create_request(client, body).json()["id"]
    with ThreadPoolExecutor() as pool:
        first = pool.submit(deliver, client)
        assert entered.wait(5)
        second = pool.submit(deliver, client)
        assert second.result().json() == {"delivered": 0, "failed": 0}
        release.set()
        assert first.result().json() == {"delivered": 1, "failed": 0}
    assert len(calls) == 1
    assert request_state(client)["delivery_status"] == "delivered"
    with app.state.session_factory() as db:
        row = db.query(Outbox).filter(Outbox.request_id == rid).one()
        assert row.receipt_id == "receipt"


def test_expired_lease_reclaimed_and_stale_failure_cannot_overwrite_success(make):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def transport(req):
        calls.append(req)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
            return httpx.Response(503)
        return httpx.Response(202, json={"receipt_id": "receipt-new"})
    app, client, _, _, body = make("expired-lease", transport)
    rid = create_request(client, body).json()["id"]
    with ThreadPoolExecutor() as pool:
        stale = pool.submit(deliver, client)
        assert entered.wait(5)
        with app.state.session_factory() as db:
            row = db.query(Outbox).filter(Outbox.request_id == rid).one()
            row.lease_until = now() - timedelta(seconds=1)
            db.commit()
        assert deliver(client).json()["delivered"] == 1
        release.set()
        assert stale.result().status_code == 200
    assert request_state(client)["delivery_status"] == "delivered"
    with app.state.session_factory() as db:
        row = db.query(Outbox).filter(Outbox.request_id == rid).one()
        assert row.receipt_id == "receipt-new"


def test_event_accept_cannot_revive_customer_cancel(make, monkeypatch):
    _, client, _, provider, body = make("transition-race")
    rid = create_request(client, body).json()["id"]
    assert deliver(client).json()["delivered"] == 1
    entered, release = threading.Event(), threading.Event()
    original = bridge_module.now
    def pause():
        entered.set()
        assert release.wait(5)
        return original()
    monkeypatch.setattr(bridge_module, "now", pause)
    with ThreadPoolExecutor() as pool:
        event = pool.submit(client.post, f"/v1/bridge/requests/{rid}/events", headers=BRIDGE,
                            json={"event_id": "accept", "provider_id": provider, "status": "accepted"})
        assert entered.wait(5)
        assert client.post(f"/v1/requests/{rid}/cancel", headers=AUTH).status_code == 200
        release.set()
        assert event.result().status_code == 409
    assert request_state(client)["status"] == "cancelled"
    assert [event["status"] for event in request_state(client)["events"]] == ["requested", "cancelled"]


def test_recorded_event_replays_after_later_customer_cancellation(make):
    _, client, _, provider, body = make("event-replay-after-cancel")
    rid = create_request(client, body).json()["id"]
    assert deliver(client).json()["delivered"] == 1
    event = {"event_id": "accept-once", "provider_id": provider, "status": "accepted", "message": "Seen"}
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers=BRIDGE, json=event).status_code == 200
    assert client.post(f"/v1/requests/{rid}/cancel", headers=AUTH).status_code == 200
    replay = client.post(f"/v1/bridge/requests/{rid}/events", headers=BRIDGE, json=event)
    assert replay.status_code == 200
    assert replay.json()["status"] == "cancelled"
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers=BRIDGE,
                       json={**event, "message": "Changed"}).status_code == 409


def test_simultaneous_identical_event_replay_returns_current_state(make, monkeypatch):
    _, client, _, provider, body = make("event-replay-race")
    rid = create_request(client, body).json()["id"]
    deliver(client)
    barrier = threading.Barrier(2)
    original = bridge_module.now
    def synchronize():
        barrier.wait(timeout=5)
        return original()
    monkeypatch.setattr(bridge_module, "now", synchronize)
    event = {"event_id": "same-event", "provider_id": provider, "status": "accepted", "message": "Okay"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(f"/v1/bridge/requests/{rid}/events", headers=BRIDGE, json=event), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert [row["status"] for row in request_state(client)["events"]] == ["requested", "accepted"]


def test_batch_rechecks_opt_in_before_second_send(make):
    entered, release = threading.Event(), threading.Event()
    sent = []
    def transport(req):
        sent.append(json.loads(req.content))
        if len(sent) == 1:
            entered.set()
            assert release.wait(5)
        return httpx.Response(202, json={"receipt_id": str(len(sent))})
    _, client, _, _, body = make("batch-optout", transport)
    create_request(client, body, "first")
    create_request(client, body, "second")
    with ThreadPoolExecutor() as pool:
        worker = pool.submit(deliver, client)
        assert entered.wait(5)
        response = client.post("/v1/bridge/providers", headers=BRIDGE, json={"source_id": "shop-1", "name": "Shop", "kind": "shop", "specialties": ["pdr"], "postal_codes": ["80202"], "public_visible": False, "accepting_requests": False})
        assert response.status_code == 200
        release.set()
        result = worker.result().json()
    assert result == {"delivered": 1, "failed": 1}
    assert len(sent) == 1


def test_retry_uses_immutable_reviewed_contact_vehicle_and_zip(make):
    seen = []
    def transport(req):
        seen.append((req.headers["Idempotency-Key"], json.loads(req.content)))
        return httpx.Response(503) if len(seen) == 1 else httpx.Response(202, json={"receipt_id": "receipt"})
    app, client, vehicle, _, body = make("snapshot", transport)
    assert client.put("/v1/profile", headers=AUTH, json={"name": "Before", "phone": "555-0100", "postal_code": "80202"}).status_code == 200
    assert client.put(f"/v1/vehicles/{vehicle}", headers=AUTH, json={"vin": "ORIGINAL"}).status_code == 200
    rid = create_request(client, body).json()["id"]
    assert deliver(client).json()["failed"] == 1
    client.put("/v1/profile", headers=AUTH, json={"name": "After", "phone": "555-0199", "postal_code": "99999"})
    client.put(f"/v1/vehicles/{vehicle}", headers=AUTH, json={"vin": "CHANGED"})
    with app.state.session_factory() as db:
        row = db.query(Outbox).filter(Outbox.request_id == rid).one()
        row.next_attempt_at = now()
        db.commit()
    assert deliver(client).json()["delivered"] == 1
    assert seen[0] == seen[1]
    assert seen[0][1]["contact"]["phone"] == "555-0100"
    assert seen[0][1]["vehicle"]["vin"] == "ORIGINAL"
    assert seen[0][1]["service_postal_code"] == "80202"


@pytest.mark.parametrize("payload", [[], None, "accepted", 42, {"receipt_id": ""}, {"receipt_id": "x" * 201}])
def test_malformed_receipt_is_retryable_and_does_not_abort_batch(make, payload):
    calls = []
    def transport(req):
        calls.append(req)
        return httpx.Response(202, json=payload) if len(calls) == 1 else httpx.Response(202, json={"receipt_id": "good"})
    app, client, _, _, body = make(f"receipt-{len(str(payload))}", transport)
    create_request(client, body, "first")
    create_request(client, body, "second")
    result = deliver(client)
    assert result.status_code == 200
    assert result.json() == {"delivered": 1, "failed": 1}
    assert len(calls) == 2
    assert {r["delivery_status"] for r in client.get("/v1/requests", headers=AUTH).json()} == {"failed", "delivered"}


def test_invalid_numeric_and_null_vehicle_update_return_safe_422(make):
    _, client, vehicle, _, _ = make("validation")
    for patch in ({"year": None}, {"nickname": None}, {"mileage": 10**40}, {"mileage": -1}):
        response = client.put(f"/v1/vehicles/{vehicle}", headers=AUTH, json=patch)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)
    assert client.put(f"/v1/vehicles/{vehicle}", headers=AUTH, json={"nickname": "Pickup"}).json()["year"] == 2020
    assert client.post("/v1/reminders", headers=AUTH, json={"vehicle_id": vehicle, "title": "Oil", "due_mileage": 10**40}).status_code == 422
    assert client.post("/v1/bridge/estimates/snapshots", headers=BRIDGE, json={"source_id": "quote", "customer_id": "alice", "vehicle_id": vehicle, "discipline": "pdr", "description": "Dent", "status": "ready", "amount_cents": 10**40}).status_code == 422
    assert client.post("/v1/bridge/providers", headers=BRIDGE, json={"source_id": "too-long", "name": "Shop", "kind": "shop", "specialties": ["pdr"], "postal_codes": ["80202"], "city": "x" * 101}).status_code == 422


def test_assistant_clarifies_missing_vehicle_specialty_or_zip(make):
    _, client, vehicle, _, _ = make("assistant-clarify", postal=None)
    no_vehicle = client.post("/v1/assistant", headers=AUTH, json={"message": "Find help for hail dents", "postal_code": "80202"}).json()
    assert no_vehicle["intent"] == "clarify"
    assert "vehicle" in no_vehicle["reply"].lower()
    no_specialty = client.post("/v1/assistant", headers=AUTH, json={"message": "Find a provider", "vehicle_id": vehicle, "postal_code": "80202"}).json()
    assert no_specialty["intent"] == "clarify"
    no_zip = client.post("/v1/assistant", headers=AUTH, json={"message": "Find hail help", "vehicle_id": vehicle}).json()
    assert no_zip["intent"] == "clarify"
    full = client.post("/v1/assistant", headers=AUTH, json={"message": "Find hail help", "vehicle_id": vehicle, "postal_code": "80202"}).json()
    assert full["intent"] == "find_provider"
    assert client.post("/v1/assistant", headers={"Authorization": "Bearer bob"}, json={"message": "Find hail help", "vehicle_id": vehicle, "postal_code": "80202"}).status_code == 404
    assert client.post("/v1/assistant", headers=AUTH, json={"message": "What should I do about a flat tire?"}).json()["intent"] == "advice"


def test_unauthenticated_and_oversized_stream_stop_before_unbounded_spool(make, monkeypatch):
    _, client, vehicle, _, _ = make("stream-upload")
    estimate = client.post("/v1/estimates", headers=AUTH, json={"vehicle_id": vehicle, "discipline": "pdr", "description": "Hail"}).json()["id"]
    app = client.app
    writes = [0]
    original = UploadFile.write
    async def count(self, data):
        writes[0] += len(data)
        return await original(self, data)
    monkeypatch.setattr(UploadFile, "write", count)
    boundary = b"BOUNDARY"
    start = b"--BOUNDARY\r\nContent-Disposition: form-data; name=\"label\"\r\n\r\nhood\r\n--BOUNDARY\r\nContent-Disposition: form-data; name=\"file\"; filename=\"huge.png\"\r\nContent-Type: image/png\r\n\r\n"
    chunks = [start] + [b"x" * (1024 * 1024) for _ in range(12)] + [b"\r\n--BOUNDARY--\r\n"]
    async def call(headers):
        index = [0]
        async def receive():
            i = index[0]
            index[0] += 1
            if i < len(chunks):
                return {"type": "http.request", "body": chunks[i], "more_body": i < len(chunks) - 1}
            return {"type": "http.disconnect"}
        sent = []
        async def send(message):
            sent.append(message)
        scope = {"type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
                 "path": f"/v1/estimates/{estimate}/photos", "raw_path": f"/v1/estimates/{estimate}/photos".encode(),
                 "query_string": b"", "root_path": "", "server": ("test", 80), "client": ("test", 1234),
                 "headers": [(b"content-type", b"multipart/form-data; boundary=BOUNDARY")] + headers}
        await app(scope, receive, send)
        return next(msg["status"] for msg in sent if msg["type"] == "http.response.start"), index[0]
    status, consumed = asyncio.run(call([]))
    assert status == 401
    assert writes[0] == 0
    assert consumed == 0
    status, consumed = asyncio.run(call([(b"authorization", b"Bearer alice")]))
    assert status == 413
    assert writes[0] <= 11 * 1024 * 1024
    assert consumed < len(chunks)
    status, consumed = asyncio.run(call([(b"authorization", b"Bearer alice"), (b"content-length", str(12 * 1024 * 1024).encode())]))
    assert status == 413
    assert consumed == 0


def test_cors_preflight_uses_explicit_origin_allowlist(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'cors.sqlite'}", environment="test",
                        cors_origins="https://preview.example", photo_dir=str(tmp_path / "photos"))
    app = create_app(settings, auth_verifier=lambda _: {"id": "a", "email": "a@test", "email_confirmed_at": "ok"})
    with TestClient(app) as client:
        approved = client.options("/v1/requests", headers={"Origin": "https://preview.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,idempotency-key,content-type"})
        assert approved.status_code == 200
        assert approved.headers["access-control-allow-origin"] == "https://preview.example"
        other = client.options("/v1/requests", headers={"Origin": "https://other.example", "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in other.headers


@pytest.mark.parametrize("upstream_status,expected", [(401, 401), (403, 401), (429, 503), (500, 503), (503, 503)])
def test_supabase_transient_failures_do_not_invalidate_customer_token(tmp_path, upstream_status, expected):
    settings = Settings(database_url=f"sqlite:///{tmp_path / f'auth-{upstream_status}.sqlite'}", environment="test",
                        supabase_url="https://auth.example", supabase_publishable_key="publishable", photo_dir=str(tmp_path / "photos"))
    auth_client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(upstream_status)))
    with TestClient(create_app(settings, auth_client=auth_client)) as client:
        assert client.get("/v1/bootstrap", headers=AUTH).status_code == expected


def test_saved_zip_clearing_and_empty_provider_areas_fail_closed(make):
    _, client, _, provider, body = make("clear-zip")
    assert client.put("/v1/profile", headers=AUTH, json={"postal_code": ""}).status_code == 200
    assert create_request(client, body, "cleared").status_code == 422
    assert client.put("/v1/profile", headers=AUTH, json={"postal_code": "80202-1234"}).json()["postal_code"] == "80202"
    response = client.post("/v1/bridge/providers", headers=BRIDGE, json={"source_id": "shop-1", "name": "Shop", "kind": "shop", "specialties": ["pdr"], "postal_codes": [], "public_visible": True, "accepting_requests": True})
    assert response.status_code == 200
    assert create_request(client, body, "no-area").status_code == 409


def test_migrated_legacy_queue_without_reviewed_zip_or_payload_fails_closed(tmp_path, monkeypatch):
    database = tmp_path / "legacy.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    alembic = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(alembic, "c327f8a76e79")
    with sqlite3.connect(database) as db:
        def insert(table, values):
            columns = ",".join(values)
            placeholders = ",".join("?" for _ in values)
            db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values()))
        insert("customers", {"id": "alice", "email": "alice@example.test", "name": "A", "phone": "",
                             "postal_code": "80202", "contact_preference": "email", "demo": 0})
        insert("vehicles", {"id": "vehicle", "customer_id": "alice", "nickname": "", "year": 2020,
                            "make": "Ford", "model": "Truck", "vin": "", "mileage": 0, "insurer": "", "policy_number": ""})
        insert("providers", {"id": "provider", "source_id": "shop", "name": "Shop", "kind": "shop",
                             "specialties": '["pdr"]', "postal_codes": '["80202"]', "city": "", "address": "",
                             "phone": "", "mobile_service": 0, "accepting_requests": 1, "public_visible": 1,
                             "demo_only": 0, "description": ""})
        insert("service_requests", {"id": "request", "customer_id": "alice", "vehicle_id": "vehicle",
                                    "provider_id": "provider", "specialty": "pdr", "description": "Dent",
                                    "preferred_time": "", "status": "requested", "delivery_status": "queued",
                                    "idempotency_key": "legacy", "payload_hash": "old",
                                    "created_at": "2026-09-13 00:00:00", "updated_at": "2026-09-13 00:00:00",
                                    "scheduled_at": None})
        insert("outbox", {"id": "outbox", "request_id": "request", "kind": "create", "attempts": 0,
                          "next_attempt_at": "2026-09-13 00:00:00", "receipt_id": None})
    command.upgrade(alembic, "head")
    sent = []
    def transport(req):
        sent.append(req)
        return httpx.Response(202, json={"receipt_id": "bad"})
    settings = Settings(database_url=f"sqlite:///{database}", environment="test",
                        bridge_url="https://fixture.invalid/requests", bridge_key="secret",
                        photo_dir=str(tmp_path / "photos"))
    with TestClient(create_app(settings, bridge_transport=httpx.MockTransport(transport))) as client:
        assert deliver(client).json() == {"delivered": 0, "failed": 1}
    assert sent == []
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT service_postal_code FROM service_requests").fetchone() == ("",)
        assert db.execute("SELECT payload, suppressed FROM outbox").fetchone() == (None, 1)


def test_numeric_boundaries_and_naive_schedule_are_validated(make):
    _, client, vehicle, provider, body = make("bounds")
    assert client.put(f"/v1/vehicles/{vehicle}", headers=AUTH, json={"mileage": 5_000_000}).status_code == 200
    assert client.put(f"/v1/vehicles/{vehicle}", headers=AUTH, json={"mileage": 5_000_001}).status_code == 422
    assert client.post("/v1/reminders", headers=AUTH, json={"vehicle_id": vehicle, "title": "Inspect", "due_mileage": 5_000_000}).status_code == 201
    assert client.post("/v1/bridge/estimates/snapshots", headers=BRIDGE, json={"source_id": "limit-quote", "customer_id": "alice", "vehicle_id": vehicle, "discipline": "pdr", "description": "Dent", "status": "ready", "amount_cents": 2_147_483_647}).status_code == 200
    rid = create_request(client, body).json()["id"]
    deliver(client)
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers=BRIDGE, json={"event_id": "accept", "provider_id": provider, "status": "accepted"}).status_code == 200
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers=BRIDGE, json={"event_id": "naive", "provider_id": provider, "status": "scheduled", "scheduled_at": "2026-09-20T12:00:00"}).status_code == 422


def test_malformed_oversized_receipt_body_is_bounded_and_later_row_runs(make):
    calls = []
    def transport(req):
        calls.append(req)
        return httpx.Response(202, json={"receipt_id": "x" * 8000}) if len(calls) == 1 else httpx.Response(202, json={"receipt_id": "good"})
    _, client, _, _, body = make("large-receipt-body", transport)
    create_request(client, body, "first")
    create_request(client, body, "second")
    assert deliver(client).json() == {"delivered": 1, "failed": 1}
    assert len(calls) == 2
