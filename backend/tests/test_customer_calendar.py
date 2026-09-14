"""Calendar access is private and never claims unverified availability."""
import hashlib
import json
import os
from uuid import uuid4
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings


def auth(customer="alice"):
    return {"Authorization": f"Bearer {customer}"}


def window():
    start = datetime.now(timezone.utc) + timedelta(days=2)
    return {"time_min": start.isoformat(), "time_max": (start + timedelta(days=2)).isoformat(),
            "duration_minutes": 60, "time_zone": "America/Denver", "day_start_hour": 9, "day_end_hour": 17}


@pytest.fixture
def calendar(tmp_path):
    supplied = os.getenv('CALENDAR_TEST_POSTGRES_URL')
    admin = None
    schema = None
    database_url = f"sqlite:///{tmp_path / 'calendar.sqlite'}"
    if supplied:
        url = make_url(supplied)
        if url.host not in ('127.0.0.1', 'localhost') or 'test' not in (url.database or ''):
            pytest.fail('Calendar tests require a disposable local PostgreSQL database.')
        schema = 'calendar_test_' + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        database_url = url.update_query_dict({'options': f'-csearch_path={schema}'}).render_as_string(hide_password=False)
    settings = Settings(database_url=database_url, environment="test", worker_enabled=False,
                        photo_dir=str(tmp_path / 'photos'), bridge_key="test", bridge_url="https://bridge.example.test/requests")
    app = create_app(settings, auth_verifier=lambda token: {"id": token, "email": f"{token}@example.test", "confirmed_at": "ok"})
    try:
        with TestClient(app) as client:
            client.put("/v1/profile", headers=auth(), json={"name": "Alice", "phone": "3035550123", "postal_code": "80202"})
            yield client, app
    finally:
        app.state.engine.dispose()
        if admin:
            with admin.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def test_unconnected_calendar_never_claims_availability(calendar):
    client, _ = calendar
    response = client.post('/v1/calendar/google/availability', headers=auth(), json=window())
    assert response.status_code in (409, 503)
    assert 'slots' not in response.json()


def test_calendar_status_is_private(calendar):
    client, _ = calendar
    assert client.get('/v1/calendar/google/status').status_code == 401


def test_disabled_calendar_returns_private_unavailable_state(calendar):
    client, _ = calendar
    response = client.get('/v1/calendar/google/status', headers=auth())
    assert response.status_code == 200
    assert response.json()['status'] == 'unavailable'
    assert response.json()['configured'] is False
    assert client.post('/v1/calendar/google/connect', headers=auth()).status_code == 503


class GoogleStub:
    def __init__(self):
        self.calls = []
        self.tags = None
        self.connections = []
        self.calendars = [{"id": "primary@example.test", "summary": "Private calendar name", "primary": True,
                           "timeZone": "America/Denver", "accessRole": "owner"}]
        self.busy = []
        self.bad_busy = None
        self.on_request = None

    def __call__(self, request):
        self.calls.append(request)
        assert request.url.host == "api.nango.dev"
        assert request.headers['Authorization'] == 'Bearer synthetic-nango-key'
        path = request.url.path
        if self.on_request:
            result = self.on_request(request)
            if result is not None:
                return result
        if path == '/connect/sessions':
            data = json.loads(request.content)
            assert data['allowed_integrations'] == ['estimoto-plus-google-calendar']
            self.tags = data['tags']
            self.connections = [{"connection_id": "own-connection", "provider_config_key": "estimoto-plus-google-calendar", "tags": dict(self.tags)}]
            return httpx.Response(201, json={"data": {"token": "short-lived", "connect_link": "https://connect.nango.dev/?session_token=short-lived",
                                                     "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}})
        if path == '/connections':
            return httpx.Response(200, json={"connections": self.connections})
        if path.startswith('/connections/'):
            if request.method == 'DELETE':
                return httpx.Response(204)
            found = next((c for c in self.connections if c['connection_id'] == path.split('/')[-1]), None)
            return httpx.Response(200 if found else 404, json=found or {})
        assert request.headers['Provider-Config-Key'] == 'estimoto-plus-google-calendar'
        assert request.headers['Connection-Id'] == 'own-connection'
        assert request.headers['Retries'] == '0'
        if path == '/proxy/calendar/v3/users/me/calendarList':
            return httpx.Response(200, json={"items": self.calendars})
        if path == '/proxy/calendar/v3/freeBusy':
            data = json.loads(request.content)
            assert [v['id'] for v in data['items']] == ['primary@example.test']
            return httpx.Response(200, json=self.bad_busy if self.bad_busy is not None else {
                'timeMin': data['timeMin'], 'timeMax': data['timeMax'],
                'calendars': {'primary@example.test': {'busy': self.busy}}})
        raise AssertionError(f'Unexpected provider operation: {request.method} {path}')


def enable(app):
    app.state.settings.calendar_enabled = True
    app.state.settings.nango_api_key = 'synthetic-nango-key'
    app.state.settings.nango_allowed_key_fingerprints = hashlib.sha256(b'synthetic-nango-key').hexdigest()
    stub = GoogleStub()
    app.state.calendar_transport = httpx.MockTransport(stub)
    return stub


def connect(client, app):
    stub = enable(app)
    attempt = client.post('/v1/calendar/google/connect', headers=auth())
    assert attempt.status_code == 200, attempt.text
    response = client.post('/v1/calendar/google/reconcile', headers=auth(), json={'attempt_id': attempt.json()['attempt_id']})
    assert response.status_code == 200, response.text
    assert response.json()['connected'] is True
    return stub, response.json()


def select_calendar(client, sync=False):
    response = client.put('/v1/calendar/google/preferences', headers=auth(), json={
        'selected_calendar_ids': ['primary@example.test'], 'time_zone': 'America/Denver', 'sync_confirmed': sync})
    assert response.status_code == 200, response.text
    return response.json()


def test_new_zone_is_unconfigured_and_explicit_utc_survives_reconnect(calendar):
    client, app = calendar
    assert client.get('/v1/calendar/google/status', headers=auth()).json()['time_zone'] == ''
    _, status = connect(client, app)
    assert status['time_zone'] == ''
    preferences = {'selected_calendar_ids': ['primary@example.test'],
                   'time_zone': 'Etc/UTC', 'sync_confirmed': False}
    saved = client.put('/v1/calendar/google/preferences', headers=auth(), json=preferences)
    assert saved.status_code == 200
    assert saved.json()['time_zone'] == 'Etc/UTC'
    assert client.delete('/v1/calendar/google/connection', headers=auth()).status_code == 200
    assert client.get('/v1/calendar/google/status', headers=auth()).json()['time_zone'] == 'Etc/UTC'
    _, reconnected = connect(client, app)
    assert reconnected['selected_calendar_ids'] == []
    assert reconnected['time_zone'] == 'Etc/UTC'


def test_connect_tags_are_server_owned_and_reconcile_rejects_foreign_attempt(calendar):
    client, app = calendar
    stub = enable(app)
    attempt = client.post('/v1/calendar/google/connect', headers=auth()).json()
    assert stub.tags == {'customer_id': 'alice', 'app': 'estimoto-plus', 'attempt_id': attempt['attempt_id'], 'environment': 'production'}
    assert client.post('/v1/calendar/google/reconcile', headers=auth('bob'), json={'attempt_id': attempt['attempt_id']}).status_code == 409
    stub.connections[0]['tags']['customer_id'] = 'bob'
    assert client.post('/v1/calendar/google/reconcile', headers=auth(), json={'attempt_id': attempt['attempt_id']}).status_code == 409
    assert client.get('/v1/calendar/google/status', headers=auth('bob')).json()['connected'] is False


def test_untrusted_connect_link_and_unpinned_key_fail_closed(calendar):
    client, app = calendar
    stub = enable(app)
    app.state.settings.nango_allowed_key_fingerprints = '0' * 64
    assert client.post('/v1/calendar/google/connect', headers=auth()).status_code == 503
    assert stub.calls == []
    app.state.settings.nango_allowed_key_fingerprints = hashlib.sha256(b'synthetic-nango-key').hexdigest()
    stub.on_request = lambda _: httpx.Response(201, json={'data': {'connect_link': 'https://attacker.test/?token=secret'}})
    response = client.post('/v1/calendar/google/connect', headers=auth())
    assert response.status_code == 503
    assert 'secret' not in response.text


def test_selected_calendar_must_be_owned_and_preferences_invalidate_generation(calendar):
    client, app = calendar
    stub, state = connect(client, app)
    assert client.put('/v1/calendar/google/preferences', headers=auth(), json={
        'selected_calendar_ids': ['foreign'], 'time_zone': 'America/Denver', 'sync_confirmed': False}).status_code == 422
    saved = select_calendar(client)
    assert saved['generation'] > state['generation']
    assert select_calendar(client)['generation'] == saved['generation']
    result = client.post('/v1/calendar/google/availability', headers=auth(), json=window())
    assert result.status_code == 200, result.text
    assert 0 < len(result.json()['slots']) <= 12
    assert 'Private calendar name' not in result.text
    assert client.delete('/v1/calendar/google/connection', headers=auth()).json() == {'disconnected': True}
    assert client.post('/v1/calendar/google/availability', headers=auth(), json=window()).status_code == 409


@pytest.mark.parametrize('bad', [{}, {'calendars': {}}, {'calendars': {'primary@example.test': {'errors': [{'reason': 'notFound'}], 'busy': []}}},
                                 {'calendars': {'primary@example.test': {'busy': [{'start': '2026-01-01T09:00:00', 'end': '2026-01-01T10:00:00'}]}}}])
def test_partial_or_malformed_freebusy_never_reports_free(calendar, bad):
    client, app = calendar
    stub, _ = connect(client, app)
    select_calendar(client)
    stub.bad_busy = bad
    response = client.post('/v1/calendar/google/availability', headers=auth(), json=window())
    assert response.status_code == 503
    assert 'slots' not in response.json()


def test_late_availability_after_disconnect_is_discarded(calendar):
    client, app = calendar
    stub, _ = connect(client, app)
    select_calendar(client)
    def disconnect_during_read(request):
        if request.url.path.endswith('/freeBusy'):
            assert client.delete('/v1/calendar/google/connection', headers=auth()).status_code == 200
    stub.on_request = disconnect_during_read
    response = client.post('/v1/calendar/google/availability', headers=auth(), json=window())
    assert response.status_code == 409
    assert 'slots' not in response.json()


def test_revoked_grant_requires_reconnect_without_exposing_provider_body(calendar):
    client, app = calendar
    stub, _ = connect(client, app)
    before = select_calendar(client)
    stub.on_request = lambda r: httpx.Response(403, json={'error': 'private provider diagnostic'}) if r.url.path.endswith('/freeBusy') else None
    response = client.post('/v1/calendar/google/availability', headers=auth(), json=window())
    assert response.status_code == 409
    state = client.get('/v1/calendar/google/status', headers=auth()).json()
    assert state['status'] == 'reconnect_required' and state['connected'] is False
    assert state['generation'] > before['generation']
    assert 'private provider diagnostic' not in response.text


def test_late_reconcile_cannot_restore_disconnected_connection(calendar):
    client, app = calendar
    stub = enable(app)
    attempt = client.post('/v1/calendar/google/connect', headers=auth()).json()['attempt_id']
    def disconnect_during_lookup(request):
        if request.url.path == '/connections':
            assert client.delete('/v1/calendar/google/connection', headers=auth()).status_code == 200
    stub.on_request = disconnect_during_lookup
    response = client.post('/v1/calendar/google/reconcile', headers=auth(), json={'attempt_id': attempt})
    assert response.status_code == 409
    assert client.get('/v1/calendar/google/status', headers=auth()).json()['connected'] is False


def test_truncated_calendar_list_and_partial_scope_fail_closed(calendar):
    client, app = calendar
    stub = enable(app)
    attempt = client.post('/v1/calendar/google/connect', headers=auth()).json()['attempt_id']
    stub.connections[0]['granted_scopes'] = ['https://www.googleapis.com/auth/calendar.calendarlist.readonly']
    assert client.post('/v1/calendar/google/reconcile', headers=auth(), json={'attempt_id': attempt}).status_code == 409
    stub.connections[0].pop('granted_scopes')
    assert client.post('/v1/calendar/google/reconcile', headers=auth(), json={'attempt_id': attempt}).status_code == 200
    stub.on_request = lambda r: httpx.Response(200, json={'items': [], 'nextPageToken': 'same'}) if r.url.path.endswith('/calendarList') else None
    assert client.get('/v1/calendar/google/calendars', headers=auth()).status_code == 503


def test_calendar_migration_and_rls_on_disposable_postgres(tmp_path):
    """A fresh forward migration matches metadata and denies untrusted SQL access."""
    import subprocess
    import sys
    from pathlib import Path
    from sqlalchemy.orm import Session
    from estimoto_plus.calendar_models import CalendarAttempt, CalendarConnection, CalendarOperation, CalendarProvision
    from estimoto_plus.models import Customer, Estimate, Photo, Vehicle, now
    from estimoto_plus.discovery_models import DirectoryBudget, DirectoryCache, PublicListing, DedicatedShop
    from estimoto_plus.capture_models import CaptureReceipt, CaptureVinSuggestion
    supplied = os.getenv('PLUS_TEST_POSTGRES_URL') or os.getenv('CALENDAR_TEST_POSTGRES_URL')
    if not supplied:
        pytest.skip('Local disposable PostgreSQL URL is required for migration/RLS proof.')
    url = make_url(supplied)
    if url.host not in ('localhost', '127.0.0.1') or 'test' not in (url.database or ''):
        pytest.fail('Use a local disposable PostgreSQL test database.')
    name = 'calendar_migration_test_' + uuid4().hex[:12]
    role = 'calendar_probe_' + uuid4().hex[:12]
    admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    with admin.connect() as db:
        db.execute(text('CREATE DATABASE ' + name))
    migrated = url.set(database=name)
    engine = create_engine(migrated)
    env = dict(os.environ, DATABASE_URL=migrated.render_as_string(hide_password=False))
    created_role = False
    try:
        for args in (['upgrade', 'head'], ['check']):
            result = subprocess.run([sys.executable, '-m', 'alembic', *args], cwd=Path(__file__).parents[1], env=env,
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stdout + result.stderr
        with Session(engine) as db:
            db.add(Customer(id='synthetic-calendar', email='test@example.test'))
            db.flush()
            db.add(Vehicle(id='synthetic-vehicle', customer_id='synthetic-calendar', year=2021, make='Toyota', model='Tacoma'))
            db.flush()
            db.add(Estimate(id='synthetic-estimate', customer_id='synthetic-calendar', vehicle_id='synthetic-vehicle', discipline='pdr', description='Synthetic'))
            db.flush()
            db.add(Photo(id='synthetic-photo', estimate_id='synthetic-estimate', label='vin', mime_type='image/jpeg', storage_name='synthetic-private', sha256='0' * 64))
            db.flush()
            db.add(CaptureReceipt(id=str(uuid4()), customer_id='synthetic-calendar', estimate_id='synthetic-estimate', capture_key='vin', payload_hash='0' * 64,
                                  claim_token=str(uuid4()), lease_until=now() + timedelta(minutes=1), result={}))
            db.add(CaptureVinSuggestion(photo_id='synthetic-photo', customer_id='synthetic-calendar', estimate_id='synthetic-estimate', photo_sha256='0' * 64, result={}))
            db.add(DirectoryBudget(day=now().date().isoformat()))
            db.add(DirectoryCache(key='zip:80204', value={}))
            db.add(PublicListing(source_id='node:1', value={}))
            db.add(DedicatedShop(customer_id='synthetic-calendar', vehicle_id='synthetic-vehicle', specialty='mechanical', source='openstreetmap', source_id='node:1'))
            db.add(CalendarConnection(customer_id='synthetic-calendar', integration_id='estimoto-plus-google-calendar', environment='production'))
            db.add(CalendarAttempt(customer_id='synthetic-calendar', generation=1, integration_id='estimoto-plus-google-calendar',
                                   environment='production', expires_at=now() + timedelta(minutes=30)))
            db.add(CalendarProvision(customer_id='synthetic-calendar', nango_connection_id='synthetic'))
            db.add(CalendarOperation(customer_id='synthetic-calendar', source_kind='request', source_id='synthetic', generation=1,
                                     nango_connection_id='synthetic', event_id='abcde', payload={}, payload_hash='0' * 64))
            db.commit()
        tables = [m.__tablename__ for m in (CalendarConnection, CalendarAttempt, CalendarProvision, CalendarOperation,
                                           DirectoryCache, PublicListing, DedicatedShop, DirectoryBudget, CaptureReceipt, CaptureVinSuggestion)]
        with engine.begin() as db:
            from alembic.script import ScriptDirectory
            expected_head = ScriptDirectory(str(Path(__file__).parents[1] / 'alembic')).get_current_head()
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == expected_head
            for table in tables:
                assert db.scalar(text('SELECT relrowsecurity FROM pg_class WHERE oid=to_regclass(:table)'), {'table': table}) is True
                assert db.scalar(text(f'SELECT count(*) FROM "{table}"')) == 1
            db.execute(text(f'CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS'))
            created_role = True
            for table in tables:
                assert db.scalar(text('SELECT has_table_privilege(:role, :table, \'SELECT\')'), {'role': role, 'table': table}) is False
                db.execute(text(f'GRANT SELECT ON "{table}" TO {role}'))
            db.execute(text(f'SET LOCAL ROLE {role}'))
            for table in tables:
                assert db.scalar(text(f'SELECT count(*) FROM "{table}"')) == 0
    finally:
        if created_role:
            with engine.begin() as db:
                db.execute(text(f'DROP OWNED BY {role}'))
                db.execute(text(f'DROP ROLE {role}'))
        engine.dispose()
        with admin.connect() as db:
            db.execute(text(f'DROP DATABASE {name} WITH (FORCE)'))
        admin.dispose()


def test_private_calendar_labels_never_enter_assistant_or_history(calendar, monkeypatch):
    client, app = calendar
    stub, _ = connect(client, app)
    marker = 'PRIVATE_CALENDAR_LABEL_SENTINEL'
    stub.calendars[0]['summary'] = marker
    assert marker in client.get('/v1/calendar/google/calendars', headers=auth()).text
    requests = []
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-model-key')
    app.state.assistant_transport = httpx.MockTransport(lambda r: (requests.append(json.loads(r.content)), httpx.Response(503))[1])
    before = len(stub.calls)
    answer = client.post('/v1/assistant', headers=auth(), json={'message': 'What does a cabin filter do?'})
    assert answer.status_code == 200 and len(requests) == 1
    assert marker not in json.dumps(requests) and marker not in answer.text
    assert len(stub.calls) == before
    history = client.get('/v1/knowledge', headers=auth())
    assert history.status_code == 200 and marker not in history.text
