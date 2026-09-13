from fastapi.testclient import TestClient
import pytest

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings


@pytest.fixture
def customer(tmp_path):
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path / "intents.sqlite"}', environment='test', bridge_url='https://fixture.invalid/receive', bridge_key='fixture-key', photo_dir=str(tmp_path / 'photos')), auth_verifier=lambda token: {'id': token, 'email': f'{token}@example.test', 'confirmed_at': 'ok'})
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer customer'
        client.put('/v1/profile', json={'name': 'Customer', 'postal_code': '80202'})
        vehicle = client.post('/v1/vehicles', json={'year': 2024, 'make': 'Toyota', 'model': 'Camry'}).json()
        yield client, vehicle['id']
    app.state.engine.dispose()


def publish(client, source, mobile=False, accepting=True):
    response = client.post('/v1/bridge/providers', headers={'X-Bridge-Key': 'fixture-key'}, json={'source_id': source, 'name': source, 'kind': 'technician' if mobile else 'shop', 'specialties': ['pdr', 'mechanical'], 'postal_codes': ['80202'], 'public_visible': True, 'accepting_requests': accepting, 'mobile_service': mobile})
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize('message', ['Find mobile dent repair', 'Connect me to a dent tech who can come to my house'])
def test_natural_language_mobile_matching_only_returns_available_mobile_providers(customer, message):
    client, vehicle = customer
    publish(client, 'Fixed shop')
    mobile = publish(client, 'Mobile technician', mobile=True)
    publish(client, 'Unavailable mobile technician', mobile=True, accepting=False)
    result = client.post('/v1/assistant', json={'message': message, 'vehicle_id': vehicle, 'postal_code': '80202', 'mobile_only': False}).json()
    assert result['intent'] == 'find_provider'
    assert [p['id'] for p in result['providers']] == [mobile['id']]
    assert client.get('/v1/requests').json() == []


def test_common_care_prompt_answers_topic_and_links_verified_video(customer):
    client, vehicle = customer
    result = client.post('/v1/assistant', json={'message': 'How do I check tire pressure?', 'vehicle_id': vehicle}).json()
    assert 'placard' in result['reply'] and 'gauge' in result['reply']
    assert result['videos'][0]['url'] == 'https://www.youtube.com/watch?v=dn0ShsQRgho'
    assert result['videos'][0]['source'].startswith('Michelin USA')


@pytest.mark.parametrize('has_context', [True, False])
def test_urgent_repair_request_prioritizes_safety_and_omits_diy_video(customer, has_context):
    client, vehicle = customer
    publish(client, 'Qualified shop')
    result = client.post('/v1/assistant', json={'message': 'Find repair for brake failure and smoke', 'vehicle_id': vehicle if has_context else None, 'postal_code': '80202' if has_context else None}).json()
    assert 'Avoid driving' in result['reply']
    assert result['videos'] == []
    assert client.get('/v1/requests').json() == []


def test_provider_rejection_is_distinct_from_an_idempotency_conflict(customer):
    client, vehicle = customer
    unavailable = publish(client, 'Provider A', accepting=False)
    available = publish(client, 'Provider B')
    body = {'vehicle_id': vehicle, 'provider_id': unavailable['id'], 'specialty': 'pdr', 'description': 'Door dent', 'share_contact': True}
    rejected = client.post('/v1/requests', headers={'Idempotency-Key': 'a'}, json=body)
    assert rejected.status_code == 409
    assert rejected.json()['code'] == 'request_not_created'
    assert client.get('/v1/requests').json() == []
    accepted = client.post('/v1/requests', headers={'Idempotency-Key': 'b'}, json={**body, 'provider_id': available['id']})
    assert accepted.status_code == 201
    conflict = client.post('/v1/requests', headers={'Idempotency-Key': 'b'}, json=body)
    assert conflict.status_code == 409
    assert conflict.json().get('code') != 'request_not_created'
