import base64
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.models import Base, Outbox, Provider, now


@pytest.fixture
def clients(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'db.sqlite'}", environment="test",
                        bridge_url="https://bridge.example/requests", bridge_key="bridge-secret",
                        photo_dir=str(tmp_path / "photos"))
    identities = {
        "alice": {"id": "alice-id", "email": "alice@example.test", "email_confirmed_at": "2026-01-01T00:00:00Z"},
        "bob": {"id": "bob-id", "email": "bob@example.test", "email_confirmed_at": "2026-01-01T00:00:00Z"},
    }
    delivered = []
    def transport(request):
        delivered.append(request)
        return httpx.Response(202, json={"receipt_id": "upstream-1"})
    app = create_app(settings, auth_verifier=lambda token: identities.get(token),
                     bridge_transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        yield client, delivered


def h(who):
    return {"Authorization": f"Bearer {who}"}


def create_vehicle(client, who="alice"):
    response = client.post("/v1/vehicles", headers=h(who), json={"year": 2020, "make": "Ford", "model": "F-150"})
    assert response.status_code == 201, response.text
    assert client.put("/v1/profile", headers=h(who), json={"postal_code": "80202"}).status_code == 200
    return response.json()["id"]


def publish(client, *, visible=True, accepting=True):
    response = client.post("/v1/bridge/providers", headers={"X-Bridge-Key": "bridge-secret"}, json={
        "source_id": "shop-1", "name": "PDR Shop", "kind": "shop", "specialties": ["pdr"],
        "postal_codes": ["80202"], "city": "Denver", "address": "1 Main St", "phone": "555-0100",
        "mobile_service": True, "accepting_requests": accepting, "public_visible": visible,
        "description": "Dent repair"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_private_crud_and_invalid_token(clients):
    client, _ = clients
    assert client.get("/v1/bootstrap").status_code == 401
    assert client.get("/v1/bootstrap", headers=h("invalid")).status_code == 401
    vehicle = create_vehicle(client)
    assert len(client.get("/v1/bootstrap", headers=h("alice")).json()["vehicles"]) == 1
    assert client.get("/v1/bootstrap", headers=h("bob")).json()["vehicles"] == []
    assert client.put(f"/v1/vehicles/{vehicle}", headers=h("bob"), json={"nickname": "Mine"}).status_code == 404
    assert client.delete(f"/v1/vehicles/{vehicle}", headers=h("bob")).status_code == 404


def test_provider_opt_in_and_exact_eligibility(clients):
    client, _ = clients
    hidden = publish(client, visible=False)
    assert client.get("/v1/providers", headers=h("alice")).json() == []
    publish(client, visible=True, accepting=False)
    assert client.get("/v1/providers?specialty=pdr&postal_code=80202&mobile_only=true", headers=h("alice")).json()[0]["id"] == hidden
    vehicle = create_vehicle(client)
    body = {"vehicle_id": vehicle, "provider_id": hidden, "specialty": "pdr", "description": "Hail dents", "preferred_time": "Weekday", "share_contact": True}
    assert client.post("/v1/requests", headers={**h("alice"), "Idempotency-Key": "one"}, json=body).status_code == 409


def test_request_idempotency_ownership_delivery_and_replay(clients):
    client, delivered = clients
    vehicle = create_vehicle(client)
    provider = publish(client)
    body = {"vehicle_id": vehicle, "provider_id": provider, "specialty": "pdr", "description": "Hail dents", "preferred_time": "Weekday", "share_contact": True}
    headers = {**h("alice"), "Idempotency-Key": "first-request"}
    first = client.post("/v1/requests", headers=headers, json=body)
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "requested"
    assert first.json()["delivery_status"] == "queued"
    assert client.get("/v1/requests", headers=h("bob")).json() == []
    assert client.post("/v1/requests", headers=headers, json=body).json()["id"] == first.json()["id"]
    assert client.post("/v1/requests", headers=headers, json={**body, "description": "Changed"}).status_code == 409
    assert len(delivered) == 0
    worker = client.post("/v1/bridge/outbox/deliver", headers={"X-Bridge-Key": "bridge-secret"})
    assert worker.status_code == 200
    assert client.get("/v1/requests", headers=h("alice")).json()[0]["delivery_status"] == "delivered"
    assert len(delivered) == 1
    rid = first.json()["id"]
    event = {"event_id": "event-1", "provider_id": provider, "status": "accepted", "message": "We can help"}
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers={"X-Bridge-Key": "bridge-secret"}, json=event).status_code == 200
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers={"X-Bridge-Key": "bridge-secret"}, json=event).status_code == 200
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers={"X-Bridge-Key": "bridge-secret"}, json={**event, "event_id": "event-2", "status": "scheduled"}).status_code == 422
    assert len(client.get("/v1/requests", headers=h("alice")).json()[0]["events"]) == 2


VALID_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qXcAAAAASUVORK5CYII=")


def test_estimate_photo_validation_and_private_retrieval(clients):
    client, _ = clients
    vehicle = create_vehicle(client)
    estimate = client.post("/v1/estimates", headers=h("alice"), json={"vehicle_id": vehicle, "discipline": "pdr", "description": "Hail"})
    assert estimate.status_code == 201
    eid = estimate.json()["id"]
    assert estimate.json()["amount_cents"] is None
    assert client.post(f"/v1/estimates/{eid}/photos", headers=h("bob"), files={"file": ("a.png", VALID_PNG, "image/png")}, data={"label": "hood"}).status_code == 404
    assert client.post(f"/v1/estimates/{eid}/photos", headers=h("alice"), files={"file": ("bad.jpg", b"<script>", "image/jpeg")}, data={"label": "hood"}).status_code == 422
    uploaded = client.post(f"/v1/estimates/{eid}/photos", headers=h("alice"), files={"file": ("a.png", VALID_PNG, "image/png")}, data={"label": "hood"})
    assert uploaded.status_code == 201, uploaded.text
    pid = uploaded.json()["id"]
    assert client.get(f"/v1/estimates/{eid}/photos/{pid}", headers=h("bob")).status_code == 404
    assert client.get(f"/v1/estimates/{eid}/photos/{pid}", headers=h("alice")).content.startswith(b"\x89PNG")


def test_missing_upstream_and_disabled_dev(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'db.sqlite'}", environment="production", photo_dir=str(tmp_path / "photos"))
    app = create_app(settings, auth_verifier=lambda _: {"id": "a", "email": "a@test", "email_confirmed_at": "ok"})
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        assert client.post("/v1/dev/session").status_code == 404
        vehicle = create_vehicle(client, "any")
        provider = client.post("/v1/bridge/providers", json={}).status_code
        assert provider == 503
        # A request cannot be minted without a live bridge.
        assert client.get("/v1/bootstrap", headers=h("any")).json()["capabilities"]["live_requests"] is False
        with app.state.session_factory() as db:
            p = Provider(source_id="manual", name="Local", kind="shop", specialties=["pdr"], postal_codes=["80202"],
                         city="Denver", address="", phone="", mobile_service=False, accepting_requests=True,
                         public_visible=True, description="")
            db.add(p)
            db.commit()
            pid = p.id
        body = {"vehicle_id": vehicle, "provider_id": pid, "specialty": "pdr", "description": "Dent", "preferred_time": "Soon", "share_contact": True}
        assert client.post("/v1/requests", headers={**h("any"), "Idempotency-Key": "no-bridge"}, json=body).status_code == 503


def test_supabase_verification_is_fixed_and_rejects_unverified(tmp_path):
    seen = []
    def auth_transport(req):
        seen.append(req)
        return httpx.Response(200, json={"id": "verified-id", "email": "v@example.test", "email_confirmed_at": "ok", "user_metadata": {"role": "admin"}})
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'auth.sqlite'}", environment="test",
                        supabase_url="https://auth.example", supabase_publishable_key="publishable", photo_dir=str(tmp_path / "photos"))
    auth_client = httpx.Client(transport=httpx.MockTransport(auth_transport))
    with TestClient(create_app(settings, auth_client=auth_client)) as client:
        assert client.get("/v1/bootstrap", headers=h("opaque")).status_code == 200
    assert len(seen) == 1
    assert str(seen[0].url) == "https://auth.example/auth/v1/user"
    assert seen[0].headers["apikey"] == "publishable"
    assert seen[0].headers["authorization"] == "Bearer opaque"
    unverified = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"id": "u", "email": "u@test", "user_metadata": {"email_confirmed_at": "ok"}})))
    with TestClient(create_app(settings, auth_client=unverified)) as client:
        assert client.get("/v1/bootstrap", headers=h("opaque")).status_code == 401


def test_demo_is_isolated_and_production_never_accepts_dev_token(tmp_path):
    dev = Settings(database_url=f"sqlite:///{tmp_path / 'dev.sqlite'}", environment="development",
                   dev_sessions_enabled=True, dev_token_secret="a" * 32, photo_dir=str(tmp_path / "photos"))
    dev_app = create_app(dev)
    Base.metadata.create_all(dev_app.state.engine)
    with TestClient(dev_app) as client:
        token = client.post("/v1/dev/session").json()["access_token"]
        response = client.get("/v1/bootstrap", headers=h(token))
        assert response.status_code == 200
        assert response.json()["capabilities"]["demo"] is True
        assert response.json()["capabilities"]["live_requests"] is False
        assert response.json()["vehicles"][0]["make"] == "Demo"
    production = Settings(database_url=f"sqlite:///{tmp_path / 'dev.sqlite'}", environment="production",
                          dev_sessions_enabled=True, dev_token_secret="a" * 32, photo_dir=str(tmp_path / "photos"))
    with TestClient(create_app(production)) as client:
        assert client.post("/v1/dev/session").status_code == 404
        assert client.get("/v1/bootstrap", headers=h(token)).status_code == 401


def test_bridge_snapshot_binding_and_request_terminal_transition(clients):
    client, _ = clients
    v = create_vehicle(client)
    b = create_vehicle(client, "bob")
    bridge = {"X-Bridge-Key": "bridge-secret"}
    snapshot = {"source_id": "quote-1", "customer_id": "alice-id", "vehicle_id": v,
                "discipline": "collision", "description": "Bridge quote", "status": "ready", "amount_cents": 12345}
    assert client.post("/v1/bridge/estimates/snapshots", headers=bridge, json={**snapshot, "vehicle_id": b}).status_code == 404
    assert client.post("/v1/bridge/estimates/snapshots", headers=bridge, json=snapshot).status_code == 200
    assert client.post("/v1/bridge/estimates/snapshots", headers=bridge, json={**snapshot, "customer_id": "bob-id", "vehicle_id": b}).status_code == 409
    assert client.get("/v1/bootstrap", headers=h("bob")).json()["estimates"] == []
    provider_id = publish(client)
    body = {"vehicle_id": v, "provider_id": provider_id, "specialty": "pdr", "description": "Dents", "preferred_time": "Friday", "share_contact": True}
    created = client.post("/v1/requests", headers={**h("alice"), "Idempotency-Key": "terminal"}, json=body).json()
    client.post("/v1/bridge/outbox/deliver", headers=bridge)
    rid = created["id"]
    declined = {"event_id": "decline-1", "provider_id": provider_id, "status": "declined", "message": "Unavailable"}
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers=bridge, json=declined).status_code == 200
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers=bridge, json={**declined, "event_id": "accept-late", "status": "accepted"}).status_code == 409
    assert client.post(f"/v1/requests/{rid}/cancel", headers=h("alice")).status_code == 409


def test_bridge_failure_retains_retryable_outbox(tmp_path):
    attempts = []
    def failing(req):
        attempts.append(req)
        return httpx.Response(502)
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'db.sqlite'}", environment="test",
                        bridge_url="https://bridge.example/requests", bridge_key="bridge-secret", photo_dir=str(tmp_path / "photos"))
    with TestClient(create_app(settings, auth_verifier=lambda _: {"id": "a", "email": "a@test", "email_confirmed_at": "ok"},
                               bridge_transport=httpx.MockTransport(failing))) as client:
        v = create_vehicle(client, "any")
        p = publish(client)
        body = {"vehicle_id": v, "provider_id": p, "specialty": "pdr", "description": "Dent", "preferred_time": "Now", "share_contact": True}
        rid = client.post("/v1/requests", headers={**h("any"), "Idempotency-Key": "retry"}, json=body).json()["id"]
        assert client.post("/v1/bridge/outbox/deliver", headers={"X-Bridge-Key": "bridge-secret"}).json() == {"delivered": 0, "failed": 1}
        assert client.get("/v1/requests", headers=h("any")).json()[0]["delivery_status"] == "failed"
        assert client.post("/v1/requests", headers={**h("any"), "Idempotency-Key": "retry"}, json=body).json()["id"] == rid
        assert len(attempts) == 1


def test_concurrent_request_submission_mints_one_row(clients):
    client, _ = clients
    v = create_vehicle(client)
    p = publish(client)
    body = {"vehicle_id": v, "provider_id": p, "specialty": "pdr", "description": "Dents", "preferred_time": "Friday", "share_contact": True}
    headers = {**h("alice"), "Idempotency-Key": "concurrent"}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: client.post("/v1/requests", headers=headers, json=body), range(8)))
    assert {response.status_code for response in results} == {201}
    assert len({response.json()["id"] for response in results}) == 1
    assert len(client.get("/v1/requests", headers=h("alice")).json()) == 1


def test_demo_provider_never_appears_for_live_customer(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'mixed.sqlite'}", environment="development",
                        dev_sessions_enabled=True, dev_token_secret="a" * 32, photo_dir=str(tmp_path / "photos"))
    demo_app = create_app(settings, auth_verifier=lambda _: {"id": "live", "email": "live@test", "email_confirmed_at": "ok"})
    Base.metadata.create_all(demo_app.state.engine)
    with TestClient(demo_app) as client:
        demo_token = client.post("/v1/dev/session").json()["access_token"]
        assert len(client.get("/v1/providers", headers=h(demo_token)).json()) == 1
        assert client.get("/v1/providers", headers=h("live-token")).json() == []


def test_png_header_without_valid_image_is_rejected(clients):
    client, _ = clients
    v = create_vehicle(client)
    eid = client.post("/v1/estimates", headers=h("alice"), json={"vehicle_id": v, "discipline": "pdr", "description": "Hail"}).json()["id"]
    response = client.post(f"/v1/estimates/{eid}/photos", headers=h("alice"),
                           files={"file": ("fake.png", b"\x89PNG\r\n\x1a\n<script>", "image/png")}, data={"label": "hood"})
    assert response.status_code == 422


def test_cancel_delivered_request_queues_bridge_cancellation(clients):
    client, delivered = clients
    v = create_vehicle(client)
    p = publish(client)
    body = {"vehicle_id": v, "provider_id": p, "specialty": "pdr", "description": "Dent", "preferred_time": "Friday", "share_contact": True}
    rid = client.post("/v1/requests", headers={**h("alice"), "Idempotency-Key": "cancel-delivered"}, json=body).json()["id"]
    bridge = {"X-Bridge-Key": "bridge-secret"}
    assert client.post("/v1/bridge/outbox/deliver", headers=bridge).json()["delivered"] == 1
    assert client.post(f"/v1/requests/{rid}/cancel", headers=h("alice")).json()["status"] == "cancelled"
    assert client.post("/v1/bridge/outbox/deliver", headers=bridge).json()["delivered"] == 1
    assert len(delivered) == 2
    assert json.loads(delivered[-1].content)["event"] == "cancelled"
    assert delivered[-1].headers["idempotency-key"] == f"cancel:{rid}"


def test_outbound_bridge_contract_over_real_socket(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    received = []
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers["Content-Length"])))) )
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"receipt_id":"socket-receipt-1"}')
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(database_url=f"sqlite:///{tmp_path / 'socket.sqlite'}", environment="test",
                            bridge_url=f"http://127.0.0.1:{server.server_port}/requests", bridge_key="bridge-secret",
                            photo_dir=str(tmp_path / "photos"))
        with TestClient(create_app(settings, auth_verifier=lambda _: {"id": "a", "email": "a@test", "email_confirmed_at": "ok"})) as client:
            v = create_vehicle(client, "any")
            p = publish(client)
            body = {"vehicle_id": v, "provider_id": p, "specialty": "pdr", "description": "Dent", "preferred_time": "Friday", "share_contact": True}
            rid = client.post("/v1/requests", headers={**h("any"), "Idempotency-Key": "socket"}, json=body).json()["id"]
            assert client.post("/v1/bridge/outbox/deliver", headers={"X-Bridge-Key": "bridge-secret"}).json()["delivered"] == 1
            assert client.get("/v1/requests", headers=h("any")).json()[0]["delivery_status"] == "delivered"
        assert len(received) == 1
        path, headers, payload = received[0]
        assert path == "/requests"
        assert headers["Idempotency-Key"] == rid
        assert headers["X-Bridge-Key"] == "bridge-secret"
        assert payload["event"] == "created"
        assert payload["provider_source_id"] == "shop-1"
        assert payload["contact"]["email"] == "a@test"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_provider_opt_out_before_delivery_blocks_send(clients):
    client, delivered = clients
    v = create_vehicle(client)
    p = publish(client)
    body = {"vehicle_id": v, "provider_id": p, "specialty": "pdr", "description": "Dent", "preferred_time": "Friday", "share_contact": True}
    client.post("/v1/requests", headers={**h("alice"), "Idempotency-Key": "opt-out"}, json=body)
    publish(client, visible=False)
    assert client.post("/v1/bridge/outbox/deliver", headers={"X-Bridge-Key": "bridge-secret"}).json()["delivered"] == 0
    assert delivered == []


def test_failed_bridge_attempt_retries_with_same_key_and_receipt(tmp_path):
    state = {"ready": False, "keys": []}
    def receiver(request):
        state["keys"].append(request.headers["Idempotency-Key"])
        return httpx.Response(202, json={"receipt_id": "durable-2"}) if state["ready"] else httpx.Response(503)
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'retry.sqlite'}", environment="test",
                        bridge_url="https://bridge.example/requests", bridge_key="bridge-secret", photo_dir=str(tmp_path / "photos"))
    app = create_app(settings, auth_verifier=lambda _: {"id": "a", "email": "a@test", "email_confirmed_at": "ok"},
                     bridge_transport=httpx.MockTransport(receiver))
    with TestClient(app) as client:
        v = create_vehicle(client, "any")
        p = publish(client)
        body = {"vehicle_id": v, "provider_id": p, "specialty": "pdr", "description": "Dent", "preferred_time": "Soon", "share_contact": True}
        rid = client.post("/v1/requests", headers={**h("any"), "Idempotency-Key": "retry-later"}, json=body).json()["id"]
        bridge = {"X-Bridge-Key": "bridge-secret"}
        assert client.post("/v1/bridge/outbox/deliver", headers=bridge).json() == {"delivered": 0, "failed": 1}
        assert client.post("/v1/bridge/outbox/deliver", headers=bridge).json() == {"delivered": 0, "failed": 0}
        with app.state.session_factory() as db:
            row = db.query(Outbox).filter(Outbox.request_id == rid).one()
            row.next_attempt_at = now()
            db.commit()
        state["ready"] = True
        assert client.post("/v1/bridge/outbox/deliver", headers=bridge).json() == {"delivered": 1, "failed": 0}
        assert client.get("/v1/requests", headers=h("any")).json()[0]["delivery_status"] == "delivered"
        assert state["keys"] == [rid, rid]


def test_request_rejects_provider_outside_saved_postal_code(clients):
    client, _ = clients
    v = create_vehicle(client)
    p = publish(client)
    assert client.put("/v1/profile", headers=h("alice"), json={"postal_code": "99999"}).status_code == 200
    body = {"vehicle_id": v, "provider_id": p, "specialty": "pdr", "description": "Dent", "preferred_time": "Friday", "share_contact": True}
    assert client.post("/v1/requests", headers={**h("alice"), "Idempotency-Key": "postal-mismatch"}, json=body).status_code == 409


def test_scheduled_event_replay_cannot_change_time(clients):
    client, _ = clients
    v = create_vehicle(client)
    p = publish(client)
    body = {"vehicle_id": v, "provider_id": p, "specialty": "pdr", "description": "Dent", "preferred_time": "Friday", "share_contact": True}
    rid = client.post("/v1/requests", headers={**h("alice"), "Idempotency-Key": "schedule-replay"}, json=body).json()["id"]
    bridge = {"X-Bridge-Key": "bridge-secret"}
    client.post("/v1/bridge/outbox/deliver", headers=bridge)
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers=bridge, json={"event_id": "accept-1", "provider_id": p, "status": "accepted", "message": "Okay"}).status_code == 200
    scheduled = {"event_id": "scheduled-1", "provider_id": p, "status": "scheduled", "message": "Confirmed", "scheduled_at": "2026-09-20T12:00:00Z"}
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers=bridge, json=scheduled).status_code == 200
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers=bridge, json=scheduled).status_code == 200
    assert client.post(f"/v1/bridge/requests/{rid}/events", headers=bridge, json={**scheduled, "scheduled_at": "2026-09-21T12:00:00Z"}).status_code == 409


def test_reminder_due_field_and_customer_ownership(clients):
    client, _ = clients
    v = create_vehicle(client)
    assert client.post("/v1/reminders", headers=h("alice"), json={"vehicle_id": v, "title": "Oil"}).status_code == 422
    created = client.post("/v1/reminders", headers=h("alice"), json={"vehicle_id": v, "title": "Oil", "due_mileage": 50000})
    assert created.status_code == 201
    assert created.json()["due_date"] is None
    rid = created.json()["id"]
    assert client.post(f"/v1/reminders/{rid}/complete", headers=h("bob")).status_code == 404
    assert client.post(f"/v1/reminders/{rid}/complete", headers=h("alice")).json()["completed"] is True
    assert client.get("/v1/bootstrap", headers=h("bob")).json()["reminders"] == []


def test_assistant_matches_without_creating_request(clients):
    client, _ = clients
    v = create_vehicle(client)
    publish(client)
    payload = {"message": "Find someone to fix hail dents", "vehicle_id": v, "postal_code": "80202"}
    answer = client.post("/v1/assistant", headers=h("alice"), json=payload)
    assert answer.status_code == 200
    assert answer.json()["intent"] == "find_provider"
    assert answer.json()["specialty"] == "pdr"
    assert len(answer.json()["providers"]) == 1
    assert answer.json()["videos"][0]["source"] == "YouTube search"
    assert client.get("/v1/requests", headers=h("alice")).json() == []
    assert client.post("/v1/assistant", headers=h("bob"), json=payload).status_code == 404
