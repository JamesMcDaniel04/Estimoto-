"""Actual Plus mode producers parsed by the original Estimoto source contracts."""
import json
import pytest
import httpx
from estimoto_plus.models import EstimateOutbox, Outbox
from estimoto_plus.schemas import EstimateSnapshot
from test_discovery import DirectoryStub
from test_estimate_delivery import plus, setup_draft, upload_keys, submit, auth, BRIDGE, KEYS
from test_original_bridge_contract import original


@pytest.mark.parametrize('mode', [None, 'shop_visit', 'mobile'])
def test_mode_producers_match_original_contract_and_legacy_omission(plus, mode):
    client, app, sent, _ = plus
    vehicle, provider, estimate = setup_draft(client)
    app.state.settings.discovery_enabled = True
    app.state.discovery_transport = httpx.MockTransport(DirectoryStub())
    assert client.post('/v1/bridge/providers', headers=BRIDGE, json={
        'source_id': 'shop-1', 'name': 'Shop', 'kind': 'shop', 'specialties': ['pdr'],
        'postal_codes': ['80221'] if mode == 'shop_visit' else ['80202'],
        'address': '1 Example St Denver CO 80221', 'mobile_service': mode == 'mobile',
        'public_visible': True, 'accepting_requests': True}).status_code == 200
    extra = {'service_mode': mode} if mode is not None else {}
    created = client.post('/v1/requests', headers={**auth(), 'Idempotency-Key': 'mode-source'}, json={
        'vehicle_id': vehicle, 'provider_id': provider, 'specialty': 'pdr', 'description': 'Review damage',
        'share_contact': True, **extra})
    assert created.status_code == 201, created.text
    upload_keys(client, estimate, (*KEYS, 'panel_hood'))
    submitted = submit(client, estimate, provider, body={'provider_id': provider, 'share_contact': True, **extra})
    assert submitted.status_code == 200, submitted.text
    with app.state.session_factory() as db:
        request_payload = db.query(Outbox).filter_by(request_id=created.json()['id']).one().payload
        estimate_payload = db.query(EstimateOutbox).filter_by(estimate_id=estimate).one().payload
        assert ('service_mode' in request_payload) == (mode is not None)
        assert ('service_mode' in estimate_payload) == (mode is not None)
        assert original('request', request_payload)['service_mode'] == mode
        assert EstimateSnapshot.model_validate(original('estimate', estimate_payload)).estimate_id == estimate
        assert 'discovery_admission' not in json.dumps(request_payload)
    # Worker uses the frozen visit proof after the customer's current profile changes.
    client.put('/v1/profile', headers=auth(), json={'name': 'Alice', 'phone': '3035550100', 'postal_code': '90210'})
    app.state.discovery_transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError('No worker geocoding')))
    client.post('/v1/bridge/outbox/deliver', headers=BRIDGE)
    client.post('/v1/bridge/estimates/deliver', headers=BRIDGE)
    assert any(r.url.path == '/bridge/plus/requests' for r in sent)
    assert any(r.url.path == '/bridge/plus/estimates' for r in sent)
