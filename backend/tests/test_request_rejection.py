from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event, Lock

from sqlalchemy.orm import Session

from test_api import clients, create_vehicle, h, publish


def test_rejected_key_stays_rejected_after_provider_returns(clients):
    client, delivered = clients
    vehicle = create_vehicle(client)
    provider = publish(client, accepting=False)
    body = {'vehicle_id': vehicle, 'provider_id': provider, 'specialty': 'pdr', 'description': 'Door dent', 'share_contact': True}
    headers = {**h('alice'), 'Idempotency-Key': 'rejected-operation'}
    rejected = client.post('/v1/requests', headers=headers, json=body)
    assert rejected.status_code == 409 and rejected.json()['code'] == 'request_not_created'
    publish(client, accepting=True)
    # A new connection models an API worker/process restart; the outcome must be durable.
    client.app.state.engine.dispose()
    replay = client.post('/v1/requests', headers=headers, json=body)
    assert replay.status_code == 409 and replay.json() == rejected.json()
    conflict = client.post('/v1/requests', headers=headers, json={**body, 'description': 'Changed request'})
    assert conflict.status_code == 409 and conflict.json().get('code') != 'request_not_created'
    assert client.get('/v1/requests', headers=h('alice')).json() == []
    assert delivered == []
    created = client.post('/v1/requests', headers={**h('alice'), 'Idempotency-Key': 'reviewed-new-operation'}, json=body)
    assert created.status_code == 201


def test_same_key_race_never_rejects_a_created_operation(clients, monkeypatch):
    client, _ = clients
    vehicle = create_vehicle(client)
    provider = publish(client)
    body = {'vehicle_id': vehicle, 'provider_id': provider, 'specialty': 'pdr', 'description': 'Door dent', 'share_contact': True}
    headers = {**h('alice'), 'Idempotency-Key': 'overlapping-operation'}
    read_done, release, second_started = Event(), Event(), Event()
    guard = Lock()
    first = True
    original = Session.scalar

    def pause_absence(session, statement, *args, **kwargs):
        nonlocal first
        result = original(session, statement, *args, **kwargs)
        sql = str(statement)
        pause = False
        if 'FROM service_requests' in sql and 'idempotency_key' in sql:
            with guard:
                if first:
                    first = False
                    pause = True
        if pause:
            assert result is None
            read_done.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(Session, 'scalar', pause_absence)

    def retry():
        second_started.set()
        return client.post('/v1/requests', headers=headers, json=body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        delayed = pool.submit(client.post, '/v1/requests', headers=headers, json=body)
        try:
            assert read_done.wait(5)
            concurrent = pool.submit(retry)
            assert second_started.wait(5)
            try:
                result = concurrent.result(timeout=0.25)
                assert result.status_code == 201
                # If a same-key creator can pass the absence read, change eligibility
                # before releasing that stale reader (the original failing interleaving).
                client.post('/v1/bridge/outbox/deliver', headers={'X-Bridge-Key': 'bridge-secret'})
                publish(client, accepting=False)
            except TimeoutError:
                pass  # Serialization may legitimately keep the retry waiting.
        finally:
            release.set()
        first_response, second_response = delayed.result(timeout=5), concurrent.result(timeout=5)
    assert first_response.status_code == second_response.status_code == 201
    assert first_response.json()['id'] == second_response.json()['id']
    publish(client, accepting=False)
    replay = client.post('/v1/requests', headers=headers, json=body)
    assert replay.status_code == 201 and replay.json()['id'] == first_response.json()['id']
    assert len(client.get('/v1/requests', headers=h('alice')).json()) == 1


def test_invalid_service_zip_rejection_stays_terminal_after_profile_edit(clients):
    client, _ = clients
    vehicle = create_vehicle(client)
    provider = publish(client)
    client.put('/v1/profile', headers=h('alice'), json={'postal_code': ''})
    body = {'vehicle_id': vehicle, 'provider_id': provider, 'specialty': 'pdr', 'description': 'Door dent', 'share_contact': True}
    headers = {**h('alice'), 'Idempotency-Key': 'missing-zip'}
    rejected = client.post('/v1/requests', headers=headers, json=body)
    assert rejected.status_code == 422
    client.put('/v1/profile', headers=h('alice'), json={'postal_code': '80202'})
    replay = client.post('/v1/requests', headers=headers, json=body)
    assert replay.status_code == 422 and replay.json() == rejected.json()
    assert client.get('/v1/requests', headers=h('alice')).json() == []
