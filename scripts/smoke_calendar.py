#!/usr/bin/env python3
"""Exercise Calendar scheduling over localhost HTTP with fictional providers.

No production credentials, Google accounts, calendars, shops or email are used.
Run with backend/.venv/bin/python scripts/smoke_calendar.py. Provider fixtures
are shared with the focused regression suite; the customer and bridge requests
travel through an actual uvicorn socket and all persisted data is temporary.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
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
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'backend/tests'))

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.calendar_sync import sync_calendar_batch
from test_customer_calendar import GoogleStub
from test_calendar_sync import CalendarWrites


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run():
    proof = {'evidence': 'localhost HTTP; synthetic Auth, Nango and shop bridge', 'checks': []}
    with tempfile.TemporaryDirectory(prefix='estimoto-plus-calendar-socket-') as directory:
        root = Path(directory)
        bridge_key = secrets.token_urlsafe(32)
        tokens = {secrets.token_urlsafe(32): 'alice', secrets.token_urlsafe(32): 'bob'}
        alice, bob = tokens
        settings = Settings(
            database_url=f'sqlite:///{root / "calendar.sqlite"}', environment='test',
            photo_dir=str(root / 'photos'), worker_enabled=False,
            bridge_key=bridge_key, bridge_url='https://bridge.example.test/requests',
            calendar_enabled=True, nango_api_key='synthetic-nango-key',
            nango_allowed_key_fingerprints=hashlib.sha256(b'synthetic-nango-key').hexdigest(),
            source_sha='fictional-socket-fixture',
        )

        def identity(token):
            name = tokens.get(token)
            return {'id': name, 'email': f'{name}@example.test', 'email_confirmed_at': 'confirmed'} if name else None

        def bridge(request):
            check(request.url.host == 'bridge.example.test', 'Unexpected outbound shop host')
            check(request.headers['X-Bridge-Key'] == bridge_key, 'Missing bridge key')
            body = json.loads(request.content)
            check('calendar_selected_ids' not in body, 'Private calendar IDs leaked to shop')
            return httpx.Response(200, json={'receipt_id': 'local-receipt-' + body['request_id']})

        app = create_app(settings, auth_verifier=identity, bridge_transport=httpx.MockTransport(bridge))
        google = GoogleStub()
        writes = CalendarWrites(google)
        app.state.calendar_transport = httpx.MockTransport(google)
        bound = socket.socket()
        bound.bind(('127.0.0.1', 0))
        port = bound.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False))
        thread = threading.Thread(target=lambda: server.run(sockets=[bound]), daemon=True)
        thread.start()
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=20, trust_env=False) as client:
                deadline = time.monotonic() + 15
                while not server.started:
                    check(thread.is_alive() and time.monotonic() < deadline, 'Local API failed to start')
                    time.sleep(.05)
                auth = {'Authorization': 'Bearer ' + alice}
                other = {'Authorization': 'Bearer ' + bob}
                staff = {'X-Bridge-Key': bridge_key}
                check(client.get('/v1/calendar/google/status').status_code == 401, 'Calendar status is public')
                check(client.put('/v1/profile', headers=auth, json={
                    'name': 'Fictional Calendar Customer', 'phone': '3035550123', 'postal_code': '80202',
                }).status_code == 200, 'Profile setup failed')
                attempt = client.post('/v1/calendar/google/connect', headers=auth).json()
                check(client.post('/v1/calendar/google/reconcile', headers=other,
                                  json={'attempt_id': attempt['attempt_id']}).status_code == 409,
                      'Another customer adopted the Google attempt')
                linked = client.post('/v1/calendar/google/reconcile', headers=auth,
                                     json={'attempt_id': attempt['attempt_id']})
                check(linked.status_code == 200 and linked.json()['connected'], 'Owned connection failed')
                prefs = client.put('/v1/calendar/google/preferences', headers=auth, json={
                    'selected_calendar_ids': ['primary@example.test'], 'time_zone': 'America/Denver', 'sync_confirmed': True,
                })
                check(prefs.status_code == 200, 'Calendar selection failed')
                start = datetime.now(timezone.utc) + timedelta(days=2)
                available = client.post('/v1/calendar/google/availability', headers=auth, json={
                    'time_min': start.isoformat(), 'time_max': (start + timedelta(days=7)).isoformat(),
                    'duration_minutes': 60, 'time_zone': 'America/Denver', 'day_start_hour': 9, 'day_end_hour': 17,
                })
                check(available.status_code == 200 and available.json()['slots'], 'No verified candidate slots')
                check('Private calendar name' not in available.text, 'Calendar text leaked into suggestions')
                slot = available.json()['slots'][0]['start']
                proof['checks'].append('Private connection, cross-customer rejection and free/busy suggestions')

                vehicle = client.post('/v1/vehicles', headers=auth, json={'year': 2020, 'make': 'Toyota', 'model': 'Camry'}).json()
                shop = client.post('/v1/bridge/providers', headers=staff, json={
                    'source_id': 'fictional-calendar-shop', 'name': 'Fictional Calendar Shop', 'kind': 'shop',
                    'specialties': ['maintenance'], 'postal_codes': ['80202'],
                    'public_visible': True, 'accepting_requests': True,
                }).json()
                body = {'vehicle_id': vehicle['id'], 'provider_id': shop['id'], 'specialty': 'maintenance',
                        'description': 'Fictional inspection', 'preferred_time': '', 'share_contact': True,
                        'calendar_check': True, 'calendar_generation': prefs.json()['generation'],
                        'duration_minutes': 60, 'proposed_slots': [slot]}
                request_headers = {**auth, 'Idempotency-Key': 'socket-calendar-request'}
                created = client.post('/v1/requests', headers=request_headers, json=body)
                check(created.status_code == 201, 'Checked request was not created')
                identifier = created.json()['id']
                check(client.post('/v1/requests', headers=request_headers, json=body).json()['id'] == identifier,
                      'Request retry duplicated the booking')
                delivery = client.post('/v1/bridge/outbox/deliver', headers=staff)
                check(delivery.status_code == 200, 'Fictional bridge delivery failed')

                def event(event_id, status, at=None):
                    data = {'event_id': event_id, 'provider_id': shop['id'], 'status': status, 'message': 'Fictional shop update'}
                    if at:
                        data['scheduled_at'] = at
                    result = client.post(f'/v1/bridge/requests/{identifier}/events', headers=staff, json=data)
                    check(result.status_code == 200, f'Actual {status} bridge route failed: {result.status_code}')
                    return result

                event('socket-accepted', 'accepted')
                event('socket-scheduled', 'scheduled', slot)
                sync_calendar_batch(settings, app.state.session_factory, app.state.calendar_transport)
                check(writes.event_posts == 1, 'Confirmed booking did not create exactly one Calendar copy')
                event_id = next(iter(writes.events))
                moved = (datetime.fromisoformat(slot) + timedelta(hours=2)).isoformat()
                event('socket-rescheduled', 'scheduled', moved)
                sync_calendar_batch(settings, app.state.session_factory, app.state.calendar_transport)
                check(writes.puts == 1 and next(iter(writes.events)) == event_id, 'Reschedule did not update the same event')
                check(writes.events[event_id]['start']['dateTime'] == moved, 'Calendar copy retained the old time')
                event('socket-cancelled', 'cancelled')
                sync_calendar_batch(settings, app.state.session_factory, app.state.calendar_transport)
                check(writes.deletes == 1 and not writes.events, 'Cancellation did not remove its app-owned event')
                proof['checks'].append('HTTP request replay, bridge delivery, confirmation, reschedule and cancellation with one event ID')

                check(client.delete('/v1/calendar/google/connection', headers=auth).status_code == 200, 'Disconnect failed')
                check(client.get('/v1/calendar/google/status', headers=auth).json()['connected'] is False, 'Disconnect did not clear binding')
                check(client.get('/v1/requests', headers=other).json() == [], 'Another customer could read appointments')
                proof['checks'].append('Disconnect and customer appointment isolation')
                proof.update(status='passed', calendar_posts=writes.calendar_posts,
                             event_posts=writes.event_posts, event_updates=writes.puts, event_deletes=writes.deletes)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            bound.close()
            app.state.engine.dispose()
            check(not thread.is_alive(), 'Local server did not stop')
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    run()
