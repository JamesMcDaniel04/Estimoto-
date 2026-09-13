"""The Plus worker pulls only authenticated, bound provider and request state."""
import json
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings

BRIDGE = {"X-Bridge-Key": "bridge-key"}
AUTH = {"Authorization": "Bearer alice"}


def test_catalog_optout_and_authoritative_request_events(tmp_path):
    state = {"visible": True, "listed": True, "events": [], "wrong_receipt": False}
    def receiver(req):
        if req.method == "GET" and req.url.path == "/bridge/plus/providers":
            return httpx.Response(200, json=[{"source_id": "shop", "name": "Shop", "kind": "shop",
                                              "specialties": ["pdr"], "postal_codes": ["80202"],
                                              "public_visible": state["visible"], "accepting_requests": state["visible"]}] if state["listed"] else [])
        if req.method == "POST" and req.url.path == "/bridge/plus/requests":
            return httpx.Response(202, json={"receipt_id": "durable-receipt"})
        if req.method == "GET" and req.url.path.startswith("/bridge/plus/requests/"):
            return httpx.Response(200, json={"request_id": req.url.path.rsplit("/", 1)[-1],
                                              "provider_source_id": "shop",
                                              "receipt_id": "wrong" if state["wrong_receipt"] else "durable-receipt",
                                              "status": state["events"][-1]["status"] if state["events"] else "requested",
                                              "scheduled_at": state["events"][-1].get("scheduled_at") if state["events"] else None,
                                              "updated_at": datetime.now(timezone.utc).isoformat(),
                                              "job_id": "job", "events": state["events"]})
        return httpx.Response(503)
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'plus.sqlite'}", environment="test",
                        bridge_url="https://receiver.example/bridge/plus/requests", bridge_key="bridge-key",
                        photo_dir=str(tmp_path / "photos"))
    app = create_app(settings, auth_verifier=lambda token: {"id": token, "email": f"{token}@example.test", "confirmed_at": "ok"},
                     bridge_transport=httpx.MockTransport(receiver))
    with TestClient(app) as client:
        assert client.post("/v1/bridge/sync").status_code == 401
        assert client.post("/v1/bridge/sync", headers=BRIDGE).json()["providers_synced"] is True
        assert len(client.get("/v1/providers", headers=AUTH).json()) == 1
        vehicle = client.post("/v1/vehicles", headers=AUTH, json={"year": 2020, "make": "Ford", "model": "Truck"}).json()["id"]
        client.put("/v1/profile", headers=AUTH, json={"postal_code": "80202"})
        provider = client.get("/v1/providers", headers=AUTH).json()[0]["id"]
        created = client.post("/v1/requests", headers={**AUTH, "Idempotency-Key": "created"},
                              json={"vehicle_id": vehicle, "provider_id": provider, "specialty": "pdr",
                                    "description": "Dent", "share_contact": True})
        assert created.status_code == 201
        request_id = created.json()["id"]
        assert client.post("/v1/bridge/outbox/deliver", headers=BRIDGE).json()["delivered"] == 1
        state["events"] = [
            {"event_id": "accept", "status": "accepted", "message": "Accepted", "created_at": "2026-09-13T00:00:00Z"},
            {"event_id": "schedule", "status": "scheduled", "message": "Booked review", "created_at": "2026-09-13T01:00:00Z",
             "scheduled_at": "2026-09-20T15:00:00Z"},
        ]
        synced = client.post("/v1/bridge/sync", headers=BRIDGE)
        assert synced.status_code == 200 and synced.json()["updated"] == 1
        request = client.get("/v1/requests", headers=AUTH).json()[0]
        assert request["status"] == "scheduled"
        assert len(request["events"]) == 3
        assert client.post("/v1/bridge/sync", headers=BRIDGE).json()["updated"] == 1
        assert len(client.get("/v1/requests", headers=AUTH).json()[0]["events"]) == 3
        state["visible"] = False
        state["wrong_receipt"] = True
        result = client.post("/v1/bridge/sync", headers=BRIDGE).json()
        assert result["providers_synced"] is True and result["failed"] == 1
        assert client.get("/v1/providers", headers=AUTH).json() == []
        assert client.get("/v1/requests", headers=AUTH).json()[0]["status"] == "scheduled"
        state["visible"] = True
        assert client.post("/v1/bridge/sync", headers=BRIDGE).json()["providers_synced"] is True
        assert len(client.get("/v1/providers", headers=AUTH).json()) == 1
        state["listed"] = False
        assert client.post("/v1/bridge/sync", headers=BRIDGE).json()["providers_synced"] is True
        assert client.get("/v1/providers", headers=AUTH).json() == []
