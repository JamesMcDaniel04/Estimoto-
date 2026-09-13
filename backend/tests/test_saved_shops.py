"""Saved contacts and explicitly authorized outreach never invent appointments."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings


@pytest.fixture
def shops(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-mail-key")
    monkeypatch.setenv("EMAIL_FROM", "Estimoto Plus <hello@example.test>")
    monkeypatch.setenv("SHOP_ACTION_BASE_URL", "https://plus.example.test")
    sent = []

    def mail(request):
        sent.append(request)
        return httpx.Response(200, json={"id": "email-receipt"})

    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'shops.sqlite'}", environment="test",
                              photo_dir=str(tmp_path / "photos"), bridge_key="bridge-key"),
                     auth_verifier=lambda token: {"id": token, "email": f"{token}@example.test", "confirmed_at": "ok"})
    app.state.shop_mail_transport = httpx.MockTransport(mail)
    with TestClient(app) as client:
        assert client.put("/v1/profile", headers=auth(), json={"name": "Alice", "phone": "3035550123", "postal_code": "80202"}).status_code == 200
        yield client, app, sent


def auth(customer="alice"):
    return {"Authorization": f"Bearer {customer}"}


def slot(days=2):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


def create_shop(client, *, email="service@example.test", phone="3035550100", vehicle_id=None):
    body = {"name": "Neighborhood Garage", "email": email, "phone": phone,
            "address": "100 Main Street, Denver, CO", "website": "", "notes": "", "vehicle_id": vehicle_id}
    response = client.post("/v1/my-shops", headers=auth(), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def draft(client, shop_id, proposed_slots=None, *, key="draft-1", vehicle_id=None):
    return client.post("/v1/shop-outreach", headers={**auth(), "Idempotency-Key": key}, json={
        "shop_id": shop_id, "vehicle_id": vehicle_id, "service_summary": "Please inspect an intermittent noise.",
        "customer_message": "I can drop the car off.", "proposed_slots": proposed_slots or [slot()]})


def authorize(client, outreach, *, key="authorize-1"):
    return client.post(f"/v1/shop-outreach/{outreach['id']}/authorize",
                       headers={**auth(), "Idempotency-Key": key},
                       json={"share_contact": True, "review_hash": outreach["review_hash"]})


def test_private_crud_immutable_review_and_explicit_authorization(shops):
    client, app, sent = shops
    client.put("/v1/profile", headers=auth(), json={"name": "Alice", "phone": "3035550123", "postal_code": "80202"})
    vehicle = client.post("/v1/vehicles", headers=auth(), json={"year": 2020, "make": "Toyota", "model": "Camry"}).json()["id"]
    shop = create_shop(client, vehicle_id=vehicle)
    assert client.get("/v1/my-shops", headers=auth("bob")).json() == []
    assert client.put(f"/v1/my-shops/{shop['id']}", headers=auth("bob"), json={"name": "Hijack"}).status_code == 404
    reviewed = draft(client, shop["id"], vehicle_id=vehicle).json()
    assert reviewed["recipient_email"] == "service@example.test"
    assert reviewed["shared_contact"]["email"] == "alice@example.test"
    assert reviewed["vehicle_summary"] == "2020 Toyota Camry"
    assert reviewed["status"] == "draft" and reviewed["delivery_status"] == "draft"
    assert sent == []
    assert draft(client, shop["id"], vehicle_id=vehicle).json()["id"] == reviewed["id"]
    assert client.put(f"/v1/my-shops/{shop['id']}", headers=auth(), json={"email": "changed@example.test"}).status_code == 200
    assert client.put("/v1/profile", headers=auth(), json={"name": "Changed", "phone": "3035550999", "postal_code": "80202"}).status_code == 200
    assert authorize(client, {**reviewed, "review_hash": "0" * 64}).status_code == 409
    assert authorize(client, reviewed).status_code == 200
    assert authorize(client, reviewed).status_code == 200
    assert authorize(client, reviewed, key="different").status_code == 409
    assert client.get(f"/v1/shop-outreach/{reviewed['id']}", headers=auth("bob")).status_code == 404
    assert client.get(f"/v1/shop-outreach/{reviewed['id']}", headers=auth()).json()["recipient_email"] == "service@example.test"
    assert sent == []
    from estimoto_plus.shop_models import ShopOutbox
    with app.state.session_factory() as db:
        rows = db.query(ShopOutbox).all()
        assert len(rows) == 1
        assert rows[0].payload["to"] == ["service@example.test"]
        assert "Changed" not in rows[0].payload["text"]


def test_phone_only_authorization_has_call_link_and_no_send(shops):
    client, app, sent = shops
    shop = create_shop(client, email="")
    reviewed = draft(client, shop["id"]).json()
    authorized = authorize(client, reviewed)
    assert authorized.status_code == 200
    assert authorized.json()["status"] == "call_required"
    assert authorized.json()["delivery_status"] == "not_sent"
    assert authorized.json()["call_link"] == "tel:3035550100"
    from estimoto_plus.shop_models import ShopOutbox
    with app.state.session_factory() as db:
        assert db.query(ShopOutbox).count() == 0
    assert sent == []


def test_shop_action_get_never_mutates_and_post_only_confirms_offered_slot(shops):
    client, app, sent = shops
    shop = create_shop(client)
    offered = slot()
    reviewed = draft(client, shop["id"], [offered]).json()
    assert authorize(client, reviewed).status_code == 200
    from estimoto_plus.saved_shops import deliver_shop_batch
    assert deliver_shop_batch(app.state.session_factory, app.state.shop_mail_transport)["delivered"] == 1
    assert len(sent) == 1
    action_url = re.search(r"https://plus\.example\.test/v1/shop-actions/[A-Za-z0-9_-]+", sent[0].read().decode()).group(0)
    action_path = action_url.removeprefix("https://plus.example.test")
    before = client.get(f"/v1/shop-outreach/{reviewed['id']}", headers=auth()).json()
    assert before["status"] == "waiting_for_reply"
    assert before["delivery_status"] == "provider_accepted"
    assert client.get(action_path).status_code == 200
    assert client.get(f"/v1/shop-outreach/{reviewed['id']}", headers=auth()).json()["status"] == "waiting_for_reply"
    assert client.post(action_path, data={"slot": slot(3)}).status_code == 422
    assert client.post(action_path, data={"slot": before["proposed_slots"][0]}).status_code == 200
    confirmed = client.get(f"/v1/shop-outreach/{reviewed['id']}", headers=auth()).json()
    assert confirmed["status"] == "confirmed" and confirmed["confirmed_slot"] == before["proposed_slots"][0]
    assert client.post(action_path, data={"slot": before["proposed_slots"][0]}).status_code == 200


def test_concurrent_authorization_one_outbox_and_cross_account_vehicle_denied(shops):
    client, app, sent = shops
    foreign_vehicle = client.post("/v1/vehicles", headers=auth("bob"), json={"year": 2020, "make": "Ford", "model": "Focus"}).json()["id"]
    assert client.post("/v1/my-shops", headers=auth(), json={"name": "A", "email": "a@example.test", "phone": "", "address": "", "vehicle_id": foreign_vehicle}).status_code == 404
    shop = create_shop(client)
    assert draft(client, shop["id"], vehicle_id=foreign_vehicle, key="wrong-vehicle").status_code == 404
    reviewed = draft(client, shop["id"]).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: authorize(client, reviewed), range(2)))
    assert [r.status_code for r in results] == [200, 200]
    from estimoto_plus.shop_models import ShopOutbox
    with app.state.session_factory() as db:
        assert db.query(ShopOutbox).count() == 1
    assert sent == []


def test_response_loss_retries_identical_mail_then_stops_after_provider_window(shops):
    from estimoto_plus.saved_shops import deliver_shop_batch
    from estimoto_plus.shop_models import ShopOutbox
    from estimoto_plus.models import now
    client, app, sent = shops
    shop = create_shop(client)
    reviewed = draft(client, shop["id"]).json()
    assert authorize(client, reviewed).status_code == 200
    attempts = []

    def lost(request):
        attempts.append(request)
        raise httpx.ReadTimeout("response lost", request=request)

    assert deliver_shop_batch(app.state.session_factory, httpx.MockTransport(lost))["delivered"] == 0
    assert client.get(f"/v1/shop-outreach/{reviewed['id']}", headers=auth()).json()["delivery_status"] == "retrying"
    with app.state.session_factory() as db:
        item = db.query(ShopOutbox).one()
        assert item.first_attempt_at is not None and item.provider_id is None
        item.next_attempt_at = now()
        db.commit()
    assert deliver_shop_batch(app.state.session_factory, app.state.shop_mail_transport)["delivered"] == 1
    assert attempts[0].headers["Idempotency-Key"] == sent[0].headers["Idempotency-Key"]
    assert attempts[0].read() == sent[0].read()

    second = draft(client, shop["id"], key="draft-2").json()
    assert authorize(client, second, key="authorize-2").status_code == 200
    assert deliver_shop_batch(app.state.session_factory, httpx.MockTransport(lost))["delivered"] == 0
    with app.state.session_factory() as db:
        item = db.query(ShopOutbox).filter(ShopOutbox.outreach_id == second["id"]).one()
        item.first_attempt_at = now() - timedelta(hours=23) + timedelta(seconds=5)
        item.next_attempt_at = now()
        db.commit()
    before = len(attempts)
    assert deliver_shop_batch(app.state.session_factory, httpx.MockTransport(lost))["unknown"] == 1
    assert len(attempts) == before
    assert client.get(f"/v1/shop-outreach/{second['id']}", headers=auth()).json()["status"] == "delivery_unknown"


def test_missing_mail_config_and_expired_action_token_fail_closed(shops, monkeypatch):
    from estimoto_plus.saved_shops import deliver_shop_batch
    from estimoto_plus.shop_models import ShopOutreach
    from estimoto_plus.models import now
    client, app, sent = shops
    shop = create_shop(client)
    reviewed = draft(client, shop["id"]).json()
    assert client.post(f"/v1/shop-outreach/{reviewed['id']}/authorize", headers={**auth("bob"), "Idempotency-Key": "bob"},
                       json={"share_contact": True, "review_hash": reviewed["review_hash"]}).status_code == 404
    monkeypatch.delenv("RESEND_API_KEY")
    assert authorize(client, reviewed).status_code == 503
    assert deliver_shop_batch(app.state.session_factory, app.state.shop_mail_transport) == {"delivered": 0, "failed": 0, "unknown": 0}
    assert sent == []
    monkeypatch.setenv("RESEND_API_KEY", "test-mail-key")
    assert authorize(client, reviewed).status_code == 200
    assert deliver_shop_batch(app.state.session_factory, app.state.shop_mail_transport)["delivered"] == 1
    action_path = re.search(r"/v1/shop-actions/[A-Za-z0-9_-]+", sent[0].read().decode()).group(0)
    with app.state.session_factory() as db:
        outreach = db.query(ShopOutreach).filter(ShopOutreach.id == reviewed["id"]).one()
        outreach.action_expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get(action_path).status_code == 404
    assert client.post(action_path, data={"slot": reviewed["proposed_slots"][0]}).status_code == 404
    assert client.get(f"/v1/shop-outreach/{reviewed['id']}", headers=auth()).json()["status"] == "waiting_for_reply"


def test_old_draft_retry_rehydrates_after_slot_window_moves(shops, monkeypatch):
    from estimoto_plus import saved_shops
    client, _, _ = shops
    shop = create_shop(client)
    offered = slot()
    reviewed = draft(client, shop["id"], [offered]).json()
    monkeypatch.setattr(saved_shops, "now", lambda: datetime.now(timezone.utc) + timedelta(days=3))
    retry = draft(client, shop["id"], [offered])
    assert retry.status_code == 201 and retry.json()["id"] == reviewed["id"]
    assert draft(client, shop["id"], [offered], key="new-key").status_code == 422
    assert authorize(client, reviewed).status_code == 422


def test_persistent_draft_quota_and_invalid_slots(shops):
    client, _, sent = shops
    shop = create_shop(client)
    assert draft(client, shop["id"], [datetime.now(timezone.utc).isoformat()], key="too-soon").status_code == 422
    assert draft(client, shop["id"], ["2026-09-20T10:00:00"], key="naive").status_code == 422
    for index in range(10):
        assert draft(client, shop["id"], key=f"draft-{index}").status_code == 201
    assert draft(client, shop["id"], key="eleventh").status_code == 429
    assert sent == []


def test_private_response_headers_and_no_unauthorized_send(shops):
    client, app, sent = shops
    shop = create_shop(client)
    reviewed = draft(client, shop["id"]).json()
    response = client.get("/v1/my-shops", headers=auth())
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert client.post("/v1/bridge/shop-outreach/deliver").status_code == 401
    assert client.post(f"/v1/shop-outreach/{reviewed['id']}/authorize", headers={**auth("bob"), "Idempotency-Key": "wrong"},
                       json={"share_contact": True, "review_hash": reviewed["review_hash"]}).status_code == 404
    assert client.post(f"/v1/shop-outreach/{reviewed['id']}/authorize", headers={**auth(), "Idempotency-Key": "wrong"},
                       json={"share_contact": False, "review_hash": reviewed["review_hash"]}).status_code == 422
    from estimoto_plus.shop_models import ShopOutbox
    with app.state.session_factory() as db:
        assert db.query(ShopOutbox).count() == 0
    assert sent == []


def test_mail_destination_and_sender_header_injection_fail_closed(shops, monkeypatch):
    client, app, sent = shops
    invalid = client.post("/v1/my-shops", headers=auth(), json={
        "name": "Garage", "email": "shop@example.test\r\nBcc:other@example.test",
        "phone": "", "address": "Denver"})
    assert invalid.status_code == 422
    shop = create_shop(client)
    reviewed = draft(client, shop["id"]).json()
    monkeypatch.setenv("EMAIL_FROM", "Estimoto <hello@example.test>\r\nBcc:other@example.test")
    assert authorize(client, reviewed).status_code == 503
    from estimoto_plus.shop_models import ShopOutbox
    with app.state.session_factory() as db:
        assert db.query(ShopOutbox).count() == 0
    assert sent == []


def test_confirmation_rejects_past_offered_slot_without_mutating(shops, monkeypatch):
    from estimoto_plus import saved_shops
    client, app, sent = shops
    shop = create_shop(client)
    offered = slot()
    reviewed = draft(client, shop["id"], [offered]).json()
    assert authorize(client, reviewed).status_code == 200
    assert saved_shops.deliver_shop_batch(app.state.session_factory, app.state.shop_mail_transport)["delivered"] == 1
    action_path = re.search(r"/v1/shop-actions/[A-Za-z0-9_-]+", sent[0].read().decode()).group(0)
    monkeypatch.setattr(saved_shops, "now", lambda: datetime.now(timezone.utc) + timedelta(days=3))
    assert client.post(action_path, data={"slot": reviewed["proposed_slots"][0]}).status_code == 422
    assert client.get(f"/v1/shop-outreach/{reviewed['id']}", headers=auth()).json()["status"] == "waiting_for_reply"


def test_delayed_worker_never_first_sends_stale_slots(shops, monkeypatch):
    from estimoto_plus import saved_shops
    client, app, sent = shops
    shop = create_shop(client)
    reviewed = draft(client, shop["id"]).json()
    assert authorize(client, reviewed).status_code == 200
    monkeypatch.setattr(saved_shops, "now", lambda: datetime.now(timezone.utc) + timedelta(days=3))
    assert saved_shops.deliver_shop_batch(app.state.session_factory, app.state.shop_mail_transport)["failed"] == 1
    assert sent == []
    state = client.get(f"/v1/shop-outreach/{reviewed['id']}", headers=auth()).json()
    assert state["status"] == "delivery_failed"
