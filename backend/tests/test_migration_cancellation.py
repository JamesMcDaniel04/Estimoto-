"""A queued cancellation must survive both pre-payload and suppressed upgrades."""
import json
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import httpx
import pytest

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings


@pytest.mark.parametrize('suppressed_before_upgrade', [False, True])
def test_legacy_cancellation_keeps_its_upstream_intent(tmp_path, monkeypatch, suppressed_before_upgrade):
    database = tmp_path / 'legacy.sqlite'
    url = f'sqlite:///{database}'
    monkeypatch.setenv('DATABASE_URL', url)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / 'alembic.ini'))
    config.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(config, 'c327f8a76e79')
    with sqlite3.connect(database) as db:
        def insert(table, values):
            db.execute(f'INSERT INTO {table} ({",".join(values)}) VALUES ({",".join("?" for _ in values)})', tuple(values.values()))
        insert('customers', dict(id='customer', email='customer@example.test', name='', phone='', postal_code='80202', contact_preference='email', demo=0))
        insert('vehicles', dict(id='vehicle', customer_id='customer', nickname='', year=2020, make='Ford', model='Truck', vin='', mileage=0, insurer='', policy_number=''))
        insert('providers', dict(id='provider', source_id='upstream-shop', name='Shop', kind='shop', specialties='["pdr"]', postal_codes='["80202"]', city='', address='', phone='', mobile_service=0, accepting_requests=0, public_visible=0, demo_only=0, description=''))
        insert('service_requests', dict(id='request', customer_id='customer', vehicle_id='vehicle', provider_id='provider', specialty='pdr', description='Dent', preferred_time='', status='cancelled', delivery_status='delivered', idempotency_key='legacy', payload_hash='old', created_at='2020-01-01 00:00:00', updated_at='2020-01-01 00:00:00', scheduled_at=None))
        insert('outbox', dict(id='creation', request_id='request', kind='create', attempts=1, next_attempt_at='2020-01-01 00:00:00', receipt_id='committed-upstream'))
        insert('outbox', dict(id='cancellation', request_id='request', kind='cancel', attempts=0, next_attempt_at='2020-01-01 00:00:00', receipt_id=None))
    command.upgrade(config, '624d7840c228')
    if suppressed_before_upgrade:
        with sqlite3.connect(database) as db:
            db.execute("UPDATE outbox SET suppressed=1 WHERE id='cancellation'")
    command.upgrade(config, 'head')
    sent = []
    def receiver(request):
        sent.append((request.headers['Idempotency-Key'], json.loads(request.content)))
        return httpx.Response(202, json={'receipt_id': 'cancel-receipt'})
    app = create_app(Settings(database_url=url, environment='development', bridge_url='https://fixture.invalid/receive', bridge_key='test-only-key', photo_dir=str(tmp_path / 'photos')), bridge_transport=httpx.MockTransport(receiver))
    with TestClient(app) as client:
        check = client.post('/v1/bridge/outbox/deliver', headers={'X-Bridge-Key': 'test-only-key'})
        assert check.status_code == 200
        assert check.json()['delivered'] == 1
        client.post('/v1/bridge/outbox/deliver', headers={'X-Bridge-Key': 'test-only-key'})
    assert sent == [('cancel:request', {'event': 'cancelled', 'request_id': 'request', 'provider_source_id': 'upstream-shop'})]
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT receipt_id,suppressed FROM outbox WHERE id='cancellation'").fetchone() == ('cancel-receipt', 0)
        assert db.execute("SELECT payload FROM outbox WHERE id='creation'").fetchone() == (None,)
    app.state.engine.dispose()
