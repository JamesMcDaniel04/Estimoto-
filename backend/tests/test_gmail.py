"""Gmail access is read-only, customer-scoped, and stores metadata only."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.gmail_models import GmailAttempt, GmailMessage
from estimoto_plus.gmail_provider import categorize
from estimoto_plus.gmail_routes import retry_gmail_revocations


def auth(customer='alice'):
    return {'Authorization': f'Bearer {customer}'}


@pytest.fixture
def gmail(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'gmail.sqlite'}", environment='test', worker_enabled=False,
                        photo_dir=str(tmp_path / 'photos'), bridge_key='test', bridge_url='https://bridge.example.test/requests')
    app = create_app(settings, auth_verifier=lambda token: {'id': token, 'email': f'{token}@example.test', 'confirmed_at': 'ok'})
    try:
        with TestClient(app) as client:
            client.put('/v1/profile', headers=auth(), json={'name': 'Alice', 'phone': '3035550123', 'postal_code': '80202'})
            client.put('/v1/profile', headers=auth('bob'), json={'name': 'Bob', 'postal_code': '80202'})
            yield client, app
    finally:
        app.state.engine.dispose()


def message(identifier, subject, sender='Demo Body Shop <service@demobodyshop.example>', snippet='Your vehicle is ready.',
            when='1757937600000'):
    return {'id': identifier, 'threadId': 't-' + identifier, 'internalDate': when, 'snippet': snippet,
            'payload': {'headers': [{'name': 'From', 'value': sender}, {'name': 'Subject', 'value': subject},
                                    {'name': 'Date', 'value': 'Mon, 15 Sep 2025 12:00:00 +0000'},
                                    {'name': 'To', 'value': 'alice@example.test'}]}}


class NangoStub:
    def __init__(self):
        self.calls = []
        self.tags = None
        self.connections = []
        self.messages = [message('m1', 'Your repair estimate is ready'),
                         message('m2', 'Receipt for invoice 4471', sender='billing@demobodyshop.example', snippet='Paid $412.50'),
                         message('m3', 'Appointment confirmed for Tuesday', sender='"Quick Lube" <hello@quicklube.example>')]
        self.on_request = None
        self.deleted = []

    def __call__(self, request):
        self.calls.append(request)
        assert request.url.host == 'api.nango.dev'
        assert request.headers['Authorization'] == 'Bearer synthetic-nango-key'
        path = request.url.path
        if self.on_request:
            result = self.on_request(request)
            if result is not None:
                return result
        if path == '/connect/sessions':
            data = json.loads(request.content)
            assert data['allowed_integrations'] == ['estimoto-plus-gmail']
            self.tags = data['tags']
            self.connections = [{'connection_id': 'mail-connection', 'provider_config_key': 'estimoto-plus-gmail', 'tags': dict(self.tags),
                                 'granted_scopes': ['https://www.googleapis.com/auth/gmail.readonly']}]
            return httpx.Response(201, json={'data': {'token': 'short', 'connect_link': 'https://connect.nango.dev/?session_token=short',
                                                     'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}})
        if path == '/connections':
            return httpx.Response(200, json={'connections': self.connections})
        if path.startswith('/connections/'):
            if request.method == 'DELETE':
                self.deleted.append(path.split('/')[-1])
                return httpx.Response(204)
            found = next((c for c in self.connections if c['connection_id'] == path.split('/')[-1]), None)
            return httpx.Response(200 if found else 404, json=found or {})
        assert request.headers['Provider-Config-Key'] == 'estimoto-plus-gmail'
        assert request.headers['Connection-Id'] == 'mail-connection'
        if path == '/proxy/gmail/v1/users/me/profile':
            return httpx.Response(200, json={'emailAddress': 'alice.driver@gmail.example', 'messagesTotal': 12})
        if path == '/proxy/gmail/v1/users/me/messages':
            assert 'newer_than:90d' in request.url.params['q'] and request.url.params['maxResults'] == '25'
            return httpx.Response(200, json={'messages': [{'id': m['id'], 'threadId': m['threadId']} for m in self.messages]})
        if path.startswith('/proxy/gmail/v1/users/me/messages/'):
            assert request.url.params['format'] == 'metadata'
            assert sorted(request.url.params.get_list('metadataHeaders')) == ['Date', 'From', 'Subject']
            found = next((m for m in self.messages if m['id'] == path.split('/')[-1]), None)
            return httpx.Response(200 if found else 404, json=found or {})
        raise AssertionError(f'Unexpected provider operation: {request.method} {path}')


def enable(app):
    app.state.settings.gmail_enabled = True
    app.state.settings.nango_api_key = 'synthetic-nango-key'
    app.state.settings.nango_allowed_key_fingerprints = hashlib.sha256(b'synthetic-nango-key').hexdigest()
    stub = NangoStub()
    app.state.gmail_transport = httpx.MockTransport(stub)
    return stub


def connect(client, app, who='alice'):
    stub = enable(app)
    attempt = client.post('/v1/mail/gmail/connect', headers=auth(who))
    assert attempt.status_code == 200, attempt.text
    assert attempt.json()['connect_link'].startswith('https://connect.nango.dev/')
    response = client.post('/v1/mail/gmail/reconcile', headers=auth(who), json={'attempt_id': attempt.json()['attempt_id']})
    assert response.status_code == 200, response.text
    return stub, response.json()


def test_status_is_private_and_honest_when_unconfigured(gmail):
    client, _ = gmail
    assert client.get('/v1/mail/gmail/status').status_code == 401
    status = client.get('/v1/mail/gmail/status', headers=auth()).json()
    assert status == {'configured': False, 'connected': False, 'status': 'unavailable', 'generation': 0, 'email_address': None,
                      'last_scan_at': None, 'attempt_id': None, 'scope': status['scope'], 'message_counts': {'new': 0, 'saved': 0, 'dismissed': 0}}
    assert client.post('/v1/mail/gmail/connect', headers=auth()).status_code == 503
    assert client.post('/v1/mail/gmail/scan', headers=auth()).status_code == 503


def test_connect_reconcile_records_address_and_rejects_foreign_attempt(gmail):
    client, app = gmail
    stub = enable(app)
    attempt = client.post('/v1/mail/gmail/connect', headers=auth()).json()
    assert stub.tags == {'customer_id': 'alice', 'app': 'estimoto-plus', 'attempt_id': attempt['attempt_id'], 'environment': 'production'}
    assert client.get('/v1/mail/gmail/status', headers=auth()).json()['status'] == 'connecting'
    assert client.post('/v1/mail/gmail/reconcile', headers=auth('bob'), json={'attempt_id': attempt['attempt_id']}).status_code == 409
    status = client.post('/v1/mail/gmail/reconcile', headers=auth(), json={'attempt_id': attempt['attempt_id']}).json()
    assert status['connected'] is True and status['status'] == 'connected'
    assert status['email_address'] == 'alice.driver@gmail.example'
    assert client.get('/v1/mail/gmail/status', headers=auth('bob')).json()['connected'] is False


def test_scan_stores_metadata_only_categorizes_and_is_customer_scoped(gmail):
    client, app = gmail
    stub, _ = connect(client, app)
    result = client.post('/v1/mail/gmail/scan', headers=auth())
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['scanned'] == 3
    rows = {m['message_id']: m for m in body['messages']}
    assert rows['m1']['category'] == 'estimate' and rows['m1']['sender_name'] == 'Demo Body Shop'
    assert rows['m1']['sender_address'] == 'service@demobodyshop.example'
    assert rows['m2']['category'] == 'receipt' and rows['m2']['snippet'] == 'Paid $412.50'
    assert rows['m3']['category'] == 'appointment' and rows['m3']['sender_name'] == 'Quick Lube'
    assert rows['m1']['received_at'].startswith('2025-09-15T12:00:00')
    assert rows['m1']['gmail_url'] == 'https://mail.google.com/mail/u/0/#all/m1'
    assert all(m['status'] == 'new' for m in body['messages'])
    assert 'alice@example.test' not in result.text  # recipient header is never kept
    with app.state.session_factory() as db:
        stored = db.scalars(select(GmailMessage)).all()
        assert {m.message_id for m in stored} == {'m1', 'm2', 'm3'}
        assert all(m.customer_id == 'alice' for m in stored)
    # A second scan fetches only unseen messages.
    fetched_before = len([c for c in stub.calls if c.url.path.startswith('/proxy/gmail/v1/users/me/messages/')])
    stub.messages.append(message('m4', 'Brake service reminder', snippet='Time for an inspection'))
    again = client.post('/v1/mail/gmail/scan', headers=auth()).json()
    assert again['scanned'] == 1 and len(again['messages']) == 4
    assert len([c for c in stub.calls if c.url.path.startswith('/proxy/gmail/v1/users/me/messages/')]) == fetched_before + 1
    status = client.get('/v1/mail/gmail/status', headers=auth()).json()
    assert status['message_counts'] == {'new': 4, 'saved': 0, 'dismissed': 0} and status['last_scan_at']
    assert client.get('/v1/mail/gmail/messages', headers=auth('bob')).status_code == 409


def test_message_status_links_owned_history_only(gmail):
    client, app = gmail
    connect(client, app)
    messages = client.post('/v1/mail/gmail/scan', headers=auth()).json()['messages']
    receipt = next(m for m in messages if m['category'] == 'receipt')
    vehicle = client.post('/v1/vehicles', headers=auth(), json={'year': 2020, 'make': 'Ford', 'model': 'F-150'}).json()['id']
    record = client.post('/v1/knowledge/records', headers={**auth(), 'Idempotency-Key': 'from-mail-1'}, json={
        'vehicle_id': vehicle, 'service_type': 'repair', 'service_date': '2025-09-15', 'cost_cents': 41250,
        'shop_name': 'Demo Body Shop', 'notes': 'Receipt for invoice 4471'}).json()
    saved = client.put(f"/v1/mail/gmail/messages/{receipt['id']}/status", headers=auth(),
                       json={'status': 'saved', 'knowledge_record_id': record['id']})
    assert saved.status_code == 200 and saved.json()['status'] == 'saved' and saved.json()['knowledge_record_id'] == record['id']
    assert client.put(f"/v1/mail/gmail/messages/{receipt['id']}/status", headers=auth('bob'), json={'status': 'dismissed'}).status_code == 409
    bob_vehicle = client.post('/v1/vehicles', headers=auth('bob'), json={'year': 2021, 'make': 'Kia', 'model': 'Soul'}).json()['id']
    foreign = client.post('/v1/knowledge/records', headers={**auth('bob'), 'Idempotency-Key': 'bob-1'}, json={
        'vehicle_id': bob_vehicle, 'service_type': 'repair', 'service_date': '2025-09-15'}).json()
    assert client.put(f"/v1/mail/gmail/messages/{receipt['id']}/status", headers=auth(),
                      json={'status': 'saved', 'knowledge_record_id': foreign['id']}).status_code == 404
    dismissed = client.put(f"/v1/mail/gmail/messages/{messages[0]['id']}/status", headers=auth(), json={'status': 'dismissed'}).json()
    assert dismissed['status'] == 'dismissed' and dismissed['knowledge_record_id'] is None
    counts = client.get('/v1/mail/gmail/status', headers=auth()).json()['message_counts']
    assert counts == {'new': 1, 'saved': 1, 'dismissed': 1}


def test_disconnect_forgets_messages_and_revokes_remotely(gmail):
    client, app = gmail
    stub, _ = connect(client, app)
    client.post('/v1/mail/gmail/scan', headers=auth())
    assert client.delete('/v1/mail/gmail/connection', headers=auth()).json() == {'disconnected': True}
    assert stub.deleted == ['mail-connection']
    status = client.get('/v1/mail/gmail/status', headers=auth()).json()
    assert status['status'] == 'disconnected' and status['email_address'] is None and status['message_counts']['new'] == 0
    with app.state.session_factory() as db:
        assert db.scalars(select(GmailMessage)).all() == []
        assert db.scalar(select(GmailAttempt)).revoke_pending is False
    assert client.get('/v1/mail/gmail/messages', headers=auth()).status_code == 409


def test_failed_revoke_is_retried_by_the_worker(gmail):
    client, app = gmail
    stub, _ = connect(client, app)
    stub.on_request = lambda request: httpx.Response(500, json={'error': 'nango down'}) if request.method == 'DELETE' else None
    assert client.delete('/v1/mail/gmail/connection', headers=auth()).status_code == 200
    with app.state.session_factory() as db:
        attempt = db.scalar(select(GmailAttempt))
        assert attempt.revoke_pending is True
        attempt.next_revoke_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    stub.on_request = None
    assert retry_gmail_revocations(app.state.settings, app.state.session_factory, app.state.gmail_transport) == 1
    assert stub.deleted == ['mail-connection']
    with app.state.session_factory() as db:
        assert db.scalar(select(GmailAttempt)).revoke_pending is False


def test_lost_grant_marks_reconnect_required_without_leaking(gmail):
    client, app = gmail
    stub, _ = connect(client, app)
    stub.connections = []
    result = client.post('/v1/mail/gmail/scan', headers=auth())
    assert result.status_code == 409
    assert 'nango' not in result.text.lower()
    assert client.get('/v1/mail/gmail/status', headers=auth()).json()['status'] == 'reconnect_required'


def test_malformed_provider_data_is_rejected_privately(gmail):
    client, app = gmail
    stub, _ = connect(client, app)
    stub.messages = [{'id': 'not valid id!', 'threadId': 'x'}]
    result = client.post('/v1/mail/gmail/scan', headers=auth())
    assert result.status_code == 503 and 'not valid id' not in result.text
    stub.messages = [message('m9', 'Estimate', when='')]
    stub.messages[0]['payload']['headers'] = [{'name': 'Subject', 'value': 'Estimate'}]
    assert client.post('/v1/mail/gmail/scan', headers=auth()).status_code == 503
    assert client.get('/v1/mail/gmail/messages', headers=auth()).json()['messages'] == []


def test_scan_rate_limit(gmail):
    client, app = gmail
    connect(client, app)
    for _ in range(6):
        assert client.post('/v1/mail/gmail/scan', headers=auth()).status_code == 200
    assert client.post('/v1/mail/gmail/scan', headers=auth()).status_code == 429


def test_categorize_prefers_receipts_then_estimates():
    assert categorize('Your estimate and receipt') == 'receipt'
    assert categorize('Quote for bumper repair') == 'estimate'
    assert categorize('Service appointment confirmed') == 'appointment'
    assert categorize('Oil change is due') == 'service'
