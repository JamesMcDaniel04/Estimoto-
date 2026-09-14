import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy import func, select

from estimoto_plus.graph import retrieve_history
from estimoto_plus.graph_models import KnowledgeConsentEvent, KnowledgePreference, KnowledgeRecord
from estimoto_plus.models import Customer
from test_api import clients, create_vehicle, h


def add(client, vehicle, who="alice", key="history-one", **fields):
    return client.post("/v1/knowledge/records", headers={**h(who), "Idempotency-Key": key}, json={
        "vehicle_id": vehicle, "service_type": "oil_change", "service_date": "2026-01-01",
        "mileage": 62000, "shop_name": "Mountain Auto", "parts_source": "NAPA",
        "parts_description": "Oil filter", "notes": "Private note with policy SECRET", **fields})


def test_private_graph_retrieval_and_source_provenance(clients, monkeypatch):
    client, _ = clients
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    vehicle = create_vehicle(client)
    record = add(client, vehicle)
    assert record.status_code == 201, record.text
    assert record.json()["source"] == "customer_reported"
    mine = client.get("/v1/knowledge", headers=h("alice")).json()
    assert mine["preferences"] == {"share_aggregate_insights": False}
    assert client.get("/v1/knowledge", headers=h("bob")).json()["records"] == []
    assert client.get("/v1/knowledge/graph", headers=h("bob")).json() == {"entities": [], "relationships": []}
    graph = client.get("/v1/knowledge/graph", headers=h("alice")).json()
    assert {e["kind"] for e in graph["entities"]} == {"vehicle", "service", "shop", "parts_supplier", "part"}
    assert {e["record_id"] for e in graph["relationships"]} == {record.json()["id"]}
    assert "SECRET" not in json.dumps(graph)
    with client.app.state.session_factory() as db:
        assert retrieve_history(db, "bob-id", vehicle, "my history") == []
        evidence = retrieve_history(db, "alice-id", vehicle, "where did I source parts?")
        assert "SECRET" not in json.dumps(evidence)
        assert evidence[0]["source_id"] == record.json()["id"]
    response = client.post("/v1/assistant", headers=h("alice"), json={"vehicle_id": vehicle, "message": "Where did I source parts for my last oil change?"})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert "NAPA" in answer["reply"] and "reported by you" in answer["reply"]
    assert answer["sources"][0]["id"] == record.json()["id"]
    assert client.post("/v1/assistant", headers=h("bob"), json={"vehicle_id": vehicle, "message": "my history"}).status_code == 404


def test_replay_and_delete_erase_projection_without_resurrection(clients):
    client, _ = clients
    vehicle = create_vehicle(client)
    first = add(client, vehicle)
    assert add(client, vehicle).json()["id"] == first.json()["id"]
    assert add(client, vehicle, shop_name="Changed").status_code == 409
    assert add(client, vehicle, who="bob").status_code == 404
    rid = first.json()["id"]
    assert client.delete(f"/v1/knowledge/records/{rid}", headers=h("bob")).status_code == 404
    assert client.delete(f"/v1/vehicles/{vehicle}", headers=h("alice")).status_code == 409
    assert client.delete(f"/v1/knowledge/records/{rid}", headers=h("alice")).status_code == 204
    assert client.get("/v1/knowledge/graph", headers=h("alice")).json() == {"entities": [], "relationships": []}
    assert add(client, vehicle).status_code == 410
    assert client.get("/v1/knowledge", headers=h("alice")).json()["records"] == []


def test_aggregate_opt_in_threshold_unique_people_and_revocation(clients):
    client, _ = clients
    identities = {f"person{i}": {"id": f"person{i}", "email": f"person{i}@example.test", "email_confirmed_at": "yes"} for i in range(10)}
    client.app.state.auth_verifier = identities.get
    for who in identities:
        vehicle = create_vehicle(client, who)
        assert add(client, vehicle, who=who).status_code == 201
        # Repeated records must not inflate distinct-person thresholds.
        assert add(client, vehicle, who=who, key="second").status_code == 201
    headers = {"X-Bridge-Key": "bridge-secret"}
    url = "/v1/bridge/knowledge/insights"
    assert client.get(url, headers=h("person1")).status_code == 401
    assert client.get(url, headers=headers).json()["service_types"] == []
    for who in list(identities)[:9]:
        assert client.put("/v1/knowledge/preferences", headers=h(who), json={"share_aggregate_insights": True}).status_code == 200
    assert client.get(url, headers=headers).json()["service_types"] == []
    client.put("/v1/knowledge/preferences", headers=h("person9"), json={"share_aggregate_insights": True})
    aggregate = client.get(url, headers=headers).json()
    assert aggregate["service_types"] == [{"category": "oil_change", "contributors_rounded": 10}]
    assert aggregate["parts_sources"] == [{"category": "NAPA", "contributors_rounded": 10}]
    assert all(s not in json.dumps(aggregate) for s in ("Mountain", "SECRET", "person", "@"))
    with client.app.state.session_factory() as db:
        db.get(KnowledgePreference, "person9").policy_version = "older-policy"
        db.commit()
    assert client.get(url, headers=headers).json()["service_types"] == []
    client.put("/v1/knowledge/preferences", headers=h("person9"), json={"share_aggregate_insights": True})
    assert client.get(url, headers=headers).json()["service_types"]
    client.put("/v1/knowledge/preferences", headers=h("person9"), json={"share_aggregate_insights": False})
    assert client.get(url, headers=headers).json()["service_types"] == []
    assert len(client.get("/v1/knowledge", headers=h("person9")).json()["records"]) == 2
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeConsentEvent)) == 12


@pytest.mark.parametrize("fields", [{"service_date": "2099-01-01"}, {"service_type": "verified_by_shop"}, {"source": "shop_verified"}, {"mileage": -1}])
def test_cannot_invent_verification_or_future_repairs(clients, fields):
    client, _ = clients
    assert add(client, create_vehicle(client), **fields).status_code == 422


def test_concurrent_first_authenticated_requests_converge(clients):
    client, _ = clients
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.get("/v1/knowledge", headers=h("alice")), range(8)))
    assert [r.status_code for r in responses] == [200] * 8
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Customer)) == 1


def test_graph_rag_model_gets_only_selected_customer_evidence(clients, monkeypatch):
    client, _ = clients
    vehicle = create_vehicle(client)
    record = add(client, vehicle).json()
    bob_vehicle = create_vehicle(client, "bob")
    add(client, bob_vehicle, who="bob", shop_name="Bob private shop")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    observed = []
    def answer(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps({"selected_source_ids": [record["id"]]})}]}]})
    client.app.state.assistant_transport = httpx.MockTransport(answer)
    result = client.post("/v1/assistant", headers=h("alice"), json={"vehicle_id": vehicle, "message": "What shop did my last oil change?"}).json()
    assert result["answer_source"] == "Your saved history"
    assert "Mountain Auto" in result["reply"] and "NAPA" in result["reply"]
    context = json.loads(observed[0]["input"])
    assert context["saved_evidence"][0]["source_id"] == record["id"]
    assert "Bob private" not in json.dumps(context) and "SECRET" not in json.dumps(context)
    assert observed[0]["store"] is False and observed[0]["tools"] == []


@pytest.mark.parametrize("model_text", ["Imaginary Auto performed your oil change", '{"selected_source_ids":["another-customer-record"]}'])
def test_generated_facts_and_unknown_sources_cannot_borrow_provenance(clients, monkeypatch, model_text):
    client, _ = clients
    vehicle = create_vehicle(client)
    add(client, vehicle)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client.app.state.assistant_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": model_text}]}]}))
    result = client.post("/v1/assistant", headers=h("alice"), json={"vehicle_id": vehicle, "message": "Which shop did my last oil change?"}).json()
    assert "Imaginary" not in result["reply"]
    assert "Mountain Auto" in result["reply"] and "reported by you" in result["reply"]


@pytest.mark.parametrize("contact", ["shop@example.test", "Shop (303) 555-0199", "https://shop.example.test"])
def test_contact_like_history_stays_in_local_answer(clients, monkeypatch, contact):
    client, _ = clients
    vehicle = create_vehicle(client)
    add(client, vehicle, shop_name=contact)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    observed = []
    client.app.state.assistant_transport = httpx.MockTransport(lambda request: observed.append(request) or httpx.Response(500))
    result = client.post("/v1/assistant", headers=h("alice"), json={"vehicle_id": vehicle, "message": "Which shop did my last oil change?"}).json()
    assert contact in result["reply"]
    assert result["answer_source"] == "Your saved history"
    assert observed == []


def test_vehicle_fields_and_question_cannot_smuggle_contacts_into_model(clients, monkeypatch):
    client, _ = clients
    vehicle = create_vehicle(client)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    observed = []
    client.app.state.assistant_transport = httpx.MockTransport(lambda request: observed.append(request) or httpx.Response(500))
    for field, text in (("make", "Jane jane.private@example.test"), ("model", "303-555-0199")):
        client.put(f"/v1/vehicles/{vehicle}", headers=h("alice"), json={field: text})
        assert client.post("/v1/assistant", headers=h("alice"), json={"vehicle_id": vehicle, "message": "What is a cabin filter?"}).status_code == 200
        client.put(f"/v1/vehicles/{vehicle}", headers=h("alice"), json={field: "Ford"})
    assert client.post("/v1/assistant", headers=h("alice"), json={"vehicle_id": vehicle, "message": "What filter fits VIN 1FTFW1ET1EKE57183?"}).status_code == 200
    assert observed == []


@pytest.mark.parametrize("message", ["Book my saved shop where I had service last time", "Please reach out to my previous shop and schedule a tire inspection"])
def test_scheduling_intent_takes_priority_over_history(clients, message):
    client, _ = clients
    vehicle = create_vehicle(client)
    result = client.post("/v1/assistant", headers=h("alice"), json={"vehicle_id": vehicle, "message": message}).json()
    assert result["intent"] == "shop_outreach"
    assert "review and authorize" in result["reply"]


def test_history_record_update_keeps_receipts_and_reprojects_graph(clients):
    client, _ = clients
    vehicle = create_vehicle(client)
    record = add(client, vehicle, shop_name="Old Shop", parts_source="Old Parts").json()
    rid = record["id"]
    from test_receipts import upload
    assert upload(client, rid).status_code == 201
    updated = client.put(f"/v1/knowledge/records/{rid}", headers=h("alice"),
                         json={"shop_name": "New Shop", "cost_cents": 12345, "notes": "changed", "mileage": 63000})
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["shop_name"] == "New Shop" and body["cost_cents"] == 12345 and body["notes"] == "changed"
    assert body["parts_source"] == "Old Parts" and len(body["receipts"]) == 1
    graph = client.get("/v1/knowledge/graph", headers=h("alice")).json()
    titles = {e["title"] for e in graph["entities"]}
    assert "New Shop" in titles and "Old Shop" not in titles
    service = next(e for e in graph["entities"] if e["kind"] == "service")
    assert service["attributes"]["mileage"] == 63000
    assert len(graph["relationships"]) == 4
    assert client.put(f"/v1/knowledge/records/{rid}", headers=h("bob"), json={"shop_name": "x"}).status_code == 404
    assert client.put(f"/v1/knowledge/records/{rid}", headers=h("alice"), json={"service_date": "2099-01-01"}).status_code == 422
    assert client.put(f"/v1/knowledge/records/{rid}", headers=h("alice"), json={"vehicle_id": "other"}).status_code == 422


@pytest.mark.parametrize('field', ['service_type', 'service_date', 'shop_name', 'parts_source', 'parts_description', 'notes'])
def test_history_required_storage_fields_reject_null(clients, field):
    client, _ = clients
    rid = add(client, create_vehicle(client)).json()['id']
    assert client.put(f'/v1/knowledge/records/{rid}', headers=h('alice'), json={field: None}).status_code == 422
