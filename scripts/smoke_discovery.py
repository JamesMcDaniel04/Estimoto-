#!/usr/bin/env python3
"""Local HTTP discovery proof with synthetic identity, directory and shop transport.

Run: backend/.venv/bin/python scripts/smoke_discovery.py
No public provider calls, real customer data or shop messages are made.
"""
import json
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
import time

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'backend/tests')]
from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.discovery_models import DirectoryBudget
from estimoto_plus.models import now
from test_discovery import DirectoryStub


def run():
    with tempfile.TemporaryDirectory(prefix='plus-discovery-socket-') as temporary:
        key = secrets.token_urlsafe(32)
        identities = {secrets.token_urlsafe(32): 'alice', secrets.token_urlsafe(32): 'bob'}
        alice, bob = identities
        sent = []
        def identity(token):
            who = identities.get(token)
            return {'id': who, 'email': who + '@example.test', 'confirmed_at': 'ok'} if who else None
        def bridge(request):
            assert request.url.host == 'bridge.example.test' and request.headers['X-Bridge-Key'] == key
            sent.append(json.loads(request.content))
            return httpx.Response(202, json={'receipt_id': 'synthetic-receipt'})
        settings = Settings(database_url=f'sqlite:///{temporary}/discovery.sqlite', photo_dir=temporary + '/photos',
                            environment='test', discovery_enabled=True, worker_enabled=False,
                            bridge_key=key, bridge_url='https://bridge.example.test/requests')
        app = create_app(settings, auth_verifier=identity, bridge_transport=httpx.MockTransport(bridge))
        stub = DirectoryStub()
        stub.elements += [stub.shop(i, f'Synthetic public garage {i}') for i in range(3, 120)]
        app.state.discovery_transport = httpx.MockTransport(stub)
        bound = socket.socket()
        bound.bind(('127.0.0.1', 0))
        port = bound.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
        thread = threading.Thread(target=lambda: server.run(sockets=[bound]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(.05)
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=15, trust_env=False) as client:
                auth, foreign, staff = {'Authorization': 'Bearer ' + alice}, {'Authorization': 'Bearer ' + bob}, {'X-Bridge-Key': key}
                assert client.get('/v1/discovery').status_code == 401
                assert client.put('/v1/profile', headers=auth, json={'name': 'Synthetic Customer', 'phone': '3035550123', 'postal_code': '80204'}).status_code == 200
                vehicle = client.post('/v1/vehicles', headers=auth, json={'year': 2022, 'make': 'Audi', 'model': 'Q5'}).json()['id']
                provider = client.post('/v1/bridge/providers', headers=staff, json={
                    'source_id': 'synthetic-partner', 'name': 'Synthetic Participating Dent Shop', 'kind': 'shop',
                    'postal_codes': ['80221'], 'specialties': ['pdr'], 'address': '1 Example St Denver CO 80221',
                    'public_visible': True, 'accepting_requests': True}).json()['id']
                params = {'vehicle_id': vehicle, 'specialty': 'pdr', 'mobile_only': True}
                result = client.get('/v1/discovery', headers=auth, params=params)
                assert result.status_code == 200, result.text
                data = result.json()
                assert data['providers'] == [] and data['shop_visit_alternatives'][0]['id'] == provider
                assert len(data['shop_visit_alternatives']) == 100 and data['truncated'] and not data['exhaustive']
                assert data['shop_visit_alternatives'][0]['request_modes'] == ['shop_visit']
                assert client.get('/v1/discovery', headers=foreign, params=params).status_code == 404
                favorite = {'vehicle_id': vehicle, 'source': 'estimoto', 'source_id': 'synthetic-partner'}
                assert client.put('/v1/discovery/favorites/pdr', headers=auth, json=favorite).status_code == 200
                assert client.get('/v1/discovery/favorites', headers=foreign, params={'vehicle_id': vehicle}).status_code == 404
                reply = client.post('/v1/assistant', headers=auth, json={'message': 'Find mobile dent repair', 'vehicle_id': vehicle}).json()
                assert 'Synthetic Participating Dent Shop' in reply['reply'] and 'shop visit' in reply['reply']
                body = {'vehicle_id': vehicle, 'provider_id': provider, 'specialty': 'pdr', 'description': 'Synthetic dent', 'share_contact': True, 'service_mode': 'shop_visit'}
                request_headers = {**auth, 'Idempotency-Key': 'synthetic-reviewed-visit'}
                created = client.post('/v1/requests', headers=request_headers, json=body)
                assert created.status_code == 201, created.text
                request_id = created.json()['id']
                assert client.post('/v1/requests', headers=request_headers, json=body).json()['id'] == request_id
                assert client.post('/v1/bridge/outbox/deliver', headers=staff).status_code == 200
                assert len(sent) == 1 and sent[0]['service_mode'] == 'shop_visit' and 'discovery_admission' not in sent[0]
                assert client.post(f'/v1/bridge/requests/{request_id}/events', headers=staff, json={
                    'event_id': 'synthetic-accepted', 'provider_id': provider, 'status': 'accepted', 'message': 'Synthetic review'}).status_code == 200
                assert client.get('/v1/requests', headers=auth).json()[0]['status'] == 'accepted'
                assert client.get('/v1/requests', headers=foreign).json() == []
                with app.state.session_factory() as db:
                    budget = db.get(DirectoryBudget, now().date().isoformat())
                    assert budget.attempts == 1 and budget.body_bytes > 0
                assert len([r for r in stub.calls if r.url.host == 'overpass-api.de']) == 1
                print(json.dumps({'status': 'passed', 'evidence': 'localhost uvicorn HTTP; synthetic directory, Auth and bridge',
                                  'combined_listings': 100, 'upstream_fixture_fetches': 1, 'synthetic_bridge_deliveries': 1,
                                  'checks': ['mobile shop-visit fallback', 'cap and source evidence', 'owned dedicated shop',
                                             'Estibot shared search', 'reviewed request replay and status', 'customer isolation', 'shared daily budget']}))
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            bound.close()
            app.state.engine.dispose()
            assert not thread.is_alive()


if __name__ == '__main__':
    run()
