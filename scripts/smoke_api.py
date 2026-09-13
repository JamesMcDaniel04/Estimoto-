#!/usr/bin/env python3
"""Boot an isolated migrated API and fictional local identity/bridge fixtures.

Run with backend/.venv/bin/python scripts/smoke_api.py [--flutter-client].
No production configuration is inherited and no external service is contacted.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def check(condition, message):
    if not condition:
        raise AssertionError(message)


@contextmanager
def fixtures():
    tokens = {secrets.token_urlsafe(24): name for name in ('socket-a', 'socket-b')}
    bridge_key = secrets.token_urlsafe(32)
    deliveries = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            name = tokens.get(self.headers.get('Authorization', '').removeprefix('Bearer '))
            if self.path != '/auth/v1/user' or name is None:
                return self.reply(401, {})
            self.reply(200, {'id': name, 'email': f'{name}@example.test', 'email_confirmed_at': '2026-09-13T00:00:00Z'})

        def do_POST(self):
            if self.path != '/receive' or self.headers.get('X-Bridge-Key') != bridge_key:
                return self.reply(401, {})
            size = int(self.headers.get('Content-Length', '0'))
            if size > 1_000_000:
                return self.reply(413, {})
            body = json.loads(self.rfile.read(size))
            key = self.headers.get('Idempotency-Key')
            if not any(item[0] == key for item in deliveries):
                deliveries.append((key, body))
            self.reply(200, {'receipt_id': f'receipt-{key}'})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', list(tokens), bridge_key, deliveries
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@contextmanager
def api_process(env, port, log_path):
    with log_path.open('a') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'estimoto_plus.app:create_app', '--factory', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT / 'backend', env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 20
            with httpx.Client(timeout=1, trust_env=False) as client:
                while time.monotonic() < deadline:
                    check(process.poll() is None, 'API process exited during startup.')
                    try:
                        if client.get(f'http://127.0.0.1:{port}/v1/bootstrap').status_code == 401:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise AssertionError('API startup timed out.')
            yield f'http://127.0.0.1:{port}'
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def run(flutter_client):
    with tempfile.TemporaryDirectory(prefix='estimoto-plus-smoke-') as directory, fixtures() as (fixture_url, tokens, bridge_key, deliveries):
        temp = Path(directory)
        env = {**os.environ, 'DATABASE_URL': f'sqlite:///{temp / "customer.sqlite"}', 'ENVIRONMENT': 'development', 'PHOTO_DIR': str(temp / 'photos'), 'SUPABASE_URL': fixture_url, 'SUPABASE_PUBLISHABLE_KEY': 'fictional-local-publishable-key', 'BRIDGE_REQUEST_URL': fixture_url + '/receive', 'BRIDGE_KEY': bridge_key, 'DEV_SESSIONS_ENABLED': 'true', 'DEV_TOKEN_SECRET': secrets.token_urlsafe(40), 'CORS_ORIGINS': 'http://127.0.0.1:4318', 'PYTHONPATH': str(ROOT / 'backend'), 'HTTP_PROXY': '', 'HTTPS_PROXY': '', 'ALL_PROXY': '', 'NO_PROXY': '127.0.0.1,localhost'}
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT / 'backend', env=env, check=True)
        subprocess.run([sys.executable, '-m', 'alembic', 'check'], cwd=ROOT / 'backend', env=env, check=True)
        port = free_port()
        auth = {'Authorization': 'Bearer ' + tokens[0]}
        bridge = {'X-Bridge-Key': bridge_key}
        with api_process(env, port, temp / 'api.log') as url, httpx.Client(base_url=url, headers=auth, timeout=10, trust_env=False) as client:
            check(client.get('/v1/bootstrap').status_code == 200, 'Identity fixture failed.')
            check(client.put('/v1/profile', json={'name': 'Socket Customer', 'postal_code': '80202'}).status_code == 200, 'Profile save failed.')
            car = client.post('/v1/vehicles', json={'year': 2024, 'make': 'Toyota', 'model': 'Camry', 'mileage': 8200}).json()
            provider = client.post('/v1/bridge/providers', headers=bridge, json={'source_id': 'socket-provider', 'name': 'Fictional Socket Dent Care', 'kind': 'technician', 'specialties': ['pdr'], 'postal_codes': ['80202'], 'public_visible': True, 'accepting_requests': True, 'mobile_service': True}).json()
            body = {'vehicle_id': car['id'], 'provider_id': provider['id'], 'specialty': 'pdr', 'description': 'Socket door dent.', 'preferred_time': 'Next week', 'share_contact': True}
            request = client.post('/v1/requests', json=body, headers={'Idempotency-Key': 'socket-request'}).json()
            replay = client.post('/v1/requests', json=body, headers={'Idempotency-Key': 'socket-request'}).json()
            check(replay['id'] == request['id'] and request['status'] == 'requested', 'Idempotent pending request failed.')
            check(client.post('/v1/bridge/outbox/deliver', headers=bridge).status_code == 200, 'Bridge delivery failed.')
            check(len(deliveries) == 1 and deliveries[0][1]['event'] == 'created', 'Fictional receiver did not persist creation.')
            state = client.get('/v1/bootstrap').json()
            check(state['requests'][0]['delivery_status'] == 'delivered' and state['requests'][0]['status'] == 'requested', 'Delivery incorrectly accepted or booked request.')
            check(client.post(f'/v1/requests/{request["id"]}/cancel').status_code == 200, 'Cancellation failed.')
            check(client.post('/v1/bridge/outbox/deliver', headers=bridge).status_code == 200, 'Cancellation delivery failed.')
            check(any(data['event'] == 'cancelled' for _, data in deliveries), 'Cancellation did not reach fictional receiver.')
            draft = client.post('/v1/estimates', json={'vehicle_id': car['id'], 'discipline': 'pdr', 'description': 'Door dent', 'date_of_loss': None}).json()
            data = BytesIO()
            Image.new('RGB', (8, 8), (20, 90, 170)).save(data, format='JPEG')
            photo = client.post(f'/v1/estimates/{draft["id"]}/photos', data={'label': 'Damage detail'}, files={'file': ('test.jpg', data.getvalue(), 'image/jpeg')}).json()
            photo_url = f'/v1/estimates/{draft["id"]}/photos/{photo["id"]}'
            image = client.get(photo_url)
            check(image.status_code == 200 and image.headers['content-type'].startswith('image/'), 'Private photo could not be read back.')
            other = {'Authorization': 'Bearer ' + tokens[1]}
            check(client.get(photo_url, headers=other).status_code == 404, 'Cross-customer photo access allowed.')
            check(client.put(f'/v1/vehicles/{car["id"]}', headers=other, json={'mileage': 1}).status_code == 404, 'Cross-customer garage edit allowed.')
            check(client.get('/v1/bootstrap', headers=other).json()['requests'] == [], 'Cross-customer request leaked.')
            if flutter_client:
                subprocess.run(['dart', 'run', 'tool/smoke_api.dart'], cwd=ROOT / 'app', env={**os.environ, 'PLUS_SMOKE_API': url}, check=True)
        with api_process(env, port, temp / 'api.log') as url, httpx.Client(base_url=url, headers=auth, timeout=10, trust_env=False) as client:
            state = client.get('/v1/bootstrap').json()
            check(any(v['id'] == car['id'] for v in state['vehicles']), 'Restart lost garage records.')
            check(state['requests'][0]['status'] == 'cancelled', 'Restart lost request cancellation.')
            check(client.get(photo_url).status_code == 200, 'Restart lost private photo.')
        print('API socket smoke: migrations, two customer identities, private photos, durable request/replay/cancel, fictional bridge receipts and restart persistence passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--flutter-client', action='store_true')
    run(parser.parse_args().flutter_client)
