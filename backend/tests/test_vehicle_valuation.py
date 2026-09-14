"""Private valuation paid-call boundaries and real database concurrency."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
import threading
from uuid import uuid4
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, text, func
from sqlalchemy.engine import make_url

from estimoto_plus import vehicle_valuation as vv
from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.models import RateBucket, Vehicle, now
from estimoto_plus.graph_models import KnowledgeRecord, KnowledgeReceipt
from estimoto_plus.valuation_models import VehicleValuationCache, ValuationProviderState

VIN = 'WBAFR7C57CC811956'  # Provider's documented public example; never a customer fixture.
BODY = {'state': 'CO', 'condition': 'clean'}


def h(who='alice'):
    return {'Authorization': 'Bearer ' + who}


def provider_data(snapshot):
    return {'input': {k: snapshot[k] for k in ('vin', 'mileage', 'state', 'condition')},
            'country': 'US', 'model_year': '2012', 'make': 'BMW', 'model': '5-Series',
            'publish_date': '4/8/2025', 'state': 'CO',
            'retail_clean': {'base_retail_clean': 9325, 'mileage_retail_clean': -300,
                             'add_deduct_retail_clean': 100, 'regional_retail_clean': 75},
            'whole_clean': {'base_whole_clean': 5300, 'mileage_whole_clean': -200,
                            'add_deduct_whole_clean': 0, 'regional_whole_clean': 0}}


def vehicle(client, who='alice', vin=VIN):
    result = client.post('/v1/vehicles', headers=h(who), json={
        'year': 2012, 'make': 'BMW', 'model': '5-Series', 'vin': vin, 'mileage': 50000})
    assert result.status_code == 201, result.text
    return result.json()['id']


@pytest.fixture(params=['sqlite', 'postgresql'])
def api(request, tmp_path, monkeypatch):
    admin = schema = None
    if request.param == 'postgresql':
        supplied = os.getenv('PLUS_TEST_POSTGRES_URL')
        if not supplied:
            pytest.skip('PLUS_TEST_POSTGRES_URL required for real concurrency proof')
        url = make_url(supplied)
        if url.host not in {'localhost', '127.0.0.1'} or 'test' not in (url.database or ''):
            pytest.fail('Use a local disposable test database')
        admin = create_engine(url)
        schema = 'plus_value_test_' + uuid4().hex
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        database_url = url.update_query_dict({'options': f'-csearch_path={schema}'}).render_as_string(hide_password=False)
    else:
        database_url = f'sqlite:///{tmp_path / "value.db"}'
    settings = Settings(database_url=database_url, environment='test', worker_enabled=False,
                        carsxe_api_key='SYNTHETIC-KEY-NOT-LIVE', valuation_enabled=True,
                        photo_dir=str(tmp_path / 'photos'))
    calls = []
    def fetch(_settings, snapshot):
        calls.append(snapshot.copy())
        return vv.ProviderResult(vv.parse_provider(provider_data(snapshot), snapshot), 86400)
    monkeypatch.setattr(vv, 'fetch_valuation', fetch)
    app = create_app(settings, auth_verifier=lambda token: {
        'id': token, 'email': token + '@example.test', 'email_confirmed_at': 'yes'} if token in {'alice', 'bob'} else None)
    if not any(getattr(route, 'path', '') == '/v1/vehicles/{vehicle_id}/valuation' for route in app.routes):
        app.include_router(vv.router)
    try:
        with TestClient(app) as client:
            yield client, calls
    finally:
        app.state.engine.dispose()
        if admin:
            with admin.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def value(client, vid, body=None, who='alice'):
    return client.post(f'/v1/vehicles/{vid}/valuation', headers=h(who), json=BODY if body is None else body)


def test_private_saved_inputs_and_cache(api):
    c, calls = api
    vid = vehicle(c)
    path = f'/v1/vehicles/{vid}/valuation'
    assert c.post(path, json=BODY).status_code == 401
    assert value(c, vid, who='bob').status_code == 404
    for body in [{**BODY, 'url': 'http://169.254.169.254'}, {**BODY, 'vin': VIN}, {**BODY, 'state': 'ZZ'},
                 {**BODY, 'condition': 'perfect'}]:
        assert value(c, vid, body).status_code == 422
    assert calls == []
    first = value(c, vid)
    assert first.status_code == 200 and first.headers['cache-control'] == 'private, no-store'
    data = first.json()
    assert data['status'] == 'available' and not data['cached']
    assert data['buckets'][0]['amount_cents'] == 920000
    assert data['buckets'][1]['kind'] == 'wholesale'
    assert 'trade-in' not in first.text and VIN not in first.text and 'SYNTHETIC-KEY' not in first.text
    assert value(c, vid).json()['cached'] is True and len(calls) == 1
    with c.app.state.session_factory() as db:
        cache = db.get(VehicleValuationCache, vid)
        assert VIN not in json.dumps(cache.payload)
        assert db.scalar(select(func.sum(RateBucket.count)).where(RateBucket.action == 'vehicle_valuation')) == 1
        db.get(Vehicle, vid).mileage = 51000
        db.commit()
    assert not value(c, vid).json()['cached'] and calls[-1]['mileage'] == 51000
    assert len(calls) == 2
    assert c.delete(f'/v1/vehicles/{vid}', headers=h()).status_code == 204
    with c.app.state.session_factory() as db:
        assert db.get(VehicleValuationCache, vid) is None


def test_history_private_cost_categories_and_saved_receipts(api):
    c, calls = api
    vid, foreign = vehicle(c), vehicle(c, 'bob')
    with c.app.state.session_factory() as db:
        for owner, vehicle_id, service, cost in [('alice', vid, 'oil_change', 12000), ('alice', vid, 'diagnostics', 7000),
              ('alice', vid, 'modification', None), ('alice', vid, 'other', 100), ('bob', foreign, 'maintenance', 999999)]:
            r = KnowledgeRecord(customer_id=owner, vehicle_id=vehicle_id, service_type=service, service_date='2026-09-01',
                                cost_cents=cost, idempotency_key=str(uuid4()), payload_hash='0'*64, notes='PRIVATE HISTORY NEVER SEND')
            db.add(r)
            db.flush()
            if service == 'oil_change':
                for status in ['saved', 'saved', 'staging', 'deleted']:
                    db.add(KnowledgeReceipt(customer_id=owner, record_id=r.id, idempotency_key=str(uuid4()),
                        payload_hash='0'*64, sha256='0'*64, filename='secret.pdf', content_type='application/pdf',
                        byte_size=100, status=status))
        db.commit()
    c.app.state.settings.valuation_enabled = False
    result = value(c, vid).json()
    assert result['status'] == 'unavailable' and calls == []
    history = result['history']
    assert history['costs_cents'] == 19100 and history['records_count'] == 4 and history['records_with_cost'] == 3
    assert history['records_with_receipts'] == 1 and history['receipt_count'] == 2
    assert {x['kind']: x['costs_cents'] for x in history['categories']} == {
        'maintenance': 12000, 'repair': 7000, 'modification': 0, 'other': 100}
    assert 'PRIVATE HISTORY' not in json.dumps(result)
    c.app.state.settings.valuation_enabled = True
    assert value(c, vid).json()['buckets'][0]['amount_cents'] == 920000
    assert set(calls[0]) == {'vehicle_id', 'vin', 'mileage', 'year', 'make', 'model', 'state', 'condition'}


def test_global_budget_negative_cache_and_per_customer_rate(api, monkeypatch):
    c, calls = api
    vid = vehicle(c)
    c.app.state.settings.valuation_daily_requests = 1
    assert value(c, vid).json()['status'] == 'available'
    assert value(c, vehicle(c, 'bob'), who='bob').json()['status'] == 'unavailable'
    assert len(calls) == 1
    c.app.state.settings.valuation_daily_requests = 20
    monkeypatch.setattr(vv, 'fetch_valuation', lambda *_: vv.ProviderResult(retry_seconds=86400))
    assert value(c, vid, {**BODY, 'state': 'CA'}).json()['status'] == 'unavailable'
    assert value(c, vid, {**BODY, 'state': 'CA'}).json()['cached']
    assert value(c, vid, {**BODY, 'state': 'AZ'}).status_code == 200
    assert value(c, vid, {**BODY, 'state': 'UT'}).status_code == 200
    assert value(c, vid, {**BODY, 'state': 'WY'}).status_code == 429
    with c.app.state.session_factory() as db:
        assert db.get(ValuationProviderState, 1).count == 4


def test_parallel_duplicate_reserves_only_one_paid_call(api, monkeypatch):
    c, calls = api
    vid = vehicle(c)
    entered, release = threading.Event(), threading.Event()
    original = vv.fetch_valuation
    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(vv, 'fetch_valuation', blocked)
    with ThreadPoolExecutor(max_workers=4) as pool:
        future = pool.submit(value, c, vid)
        assert entered.wait(5)
        pending = list(pool.map(lambda _: value(c, vid), range(3)))
        assert all(r.json()['status'] == 'pending' for r in pending)
        release.set()
        assert future.result().json()['status'] == 'available'
    assert len(calls) == 1
    assert value(c, vid).json()['cached']


def test_global_provider_backoff_and_saved_vehicle_change(api, monkeypatch):
    c, calls = api
    vid = vehicle(c)
    def failed(*_):
        return vv.ProviderResult(global_backoff=3600)
    monkeypatch.setattr(vv, 'fetch_valuation', failed)
    assert value(c, vid).json()['status'] == 'unavailable'
    with c.app.state.session_factory() as db:
        assert db.get(ValuationProviderState, 1).blocked_until is not None
    assert value(c, vehicle(c, 'bob'), who='bob').json()['status'] == 'unavailable'
    with c.app.state.session_factory() as db:
        db.get(ValuationProviderState, 1).blocked_until = now() - timedelta(seconds=1)
        db.get(VehicleValuationCache, vid).retry_at = now() - timedelta(seconds=1)
        db.commit()
    def changed(settings, snapshot):
        with c.app.state.session_factory() as db:
            db.get(Vehicle, vid).mileage += 1
            db.commit()
        return vv.ProviderResult(vv.parse_provider(provider_data(snapshot), snapshot), 86400)
    monkeypatch.setattr(vv, 'fetch_valuation', changed)
    assert value(c, vid).status_code == 422


def test_provider_parser_and_fixed_transport(monkeypatch, caplog):
    snapshot = {'vin': VIN, 'mileage': 50000, 'state': 'CO', 'condition': 'clean', 'year': 2012, 'make': 'BMW', 'model': '5-Series'}
    for mutate in [lambda d: d['input'].update(vin='1'*17), lambda d: d.update(make='Audi'),
                   lambda d: d.update(country='CA'), lambda d: d.update(retail_clean={}, whole_clean={})]:
        data = provider_data(snapshot)
        mutate(data)
        with pytest.raises(ValueError):
            vv.parse_provider(data, snapshot)
    bare = {'retail_clean': provider_data(snapshot)['retail_clean']}
    with pytest.raises(ValueError, match='identity evidence'):
        vv.parse_provider(bare, snapshot)
    data = provider_data(snapshot)
    data['retail_clean']['adjusted_retail_clean'] = 9125
    assert vv.parse_provider(data, snapshot)['buckets'][0]['amount_cents'] == 912500
    assert vv.parse_provider(data, snapshot)['buckets'][0]['amount_basis'] == 'provider_adjusted'
    data['retail_clean']['base_retail_clean'] = float('nan')
    assert [b['kind'] for b in vv.parse_provider(data, snapshot)['buckets']] == ['wholesale']
    calls = []
    def transport(url, **kwargs):
        calls.append((url, kwargs))
        return 200, json.dumps(provider_data(snapshot)).encode()
    monkeypatch.setattr(vv, '_fetch_https', transport)
    settings = Settings(carsxe_api_key='PRIVATE-SYNTHETIC-KEY')
    assert vv.fetch_valuation(settings, snapshot).payload
    assert calls[0][0].startswith('https://api.carsxe.com/v2/marketvalue?')
    assert calls[0][1]['max_bytes'] == 65536 and 'redirects' not in calls[0][1]
    assert 'PRIVATE-SYNTHETIC-KEY' not in caplog.text and VIN not in caplog.text
    for status in (301, 400, 401, 403, 404, 429, 500):
        monkeypatch.setattr(vv, '_fetch_https', lambda *_, **__: (status, b'PRIVATE'))
        result = vv.fetch_valuation(settings, snapshot)
        assert result.payload is None
        if status in {401, 403, 429}:
            assert result.global_backoff == 3600


def test_newer_lease_is_not_overwritten_and_deleted_vehicle_stays_deleted(api, monkeypatch):
    c, calls = api
    vid = vehicle(c)
    successor = str(uuid4())
    def takeover(_settings, snapshot):
        with c.app.state.session_factory() as db:
            row = db.get(VehicleValuationCache, vid)
            row.lease_token = successor
            row.lease_until = now() + timedelta(seconds=60)
            db.commit()
        return vv.ProviderResult(vv.parse_provider(provider_data(snapshot), snapshot), 86400)
    monkeypatch.setattr(vv, 'fetch_valuation', takeover)
    assert value(c, vid).json()['status'] == 'pending'
    with c.app.state.session_factory() as db:
        assert db.get(VehicleValuationCache, vid).lease_token == successor
        assert db.get(VehicleValuationCache, vid).payload is None
        db.get(VehicleValuationCache, vid).lease_until = now() - timedelta(seconds=1)
        db.commit()
    def delete_during_lookup(*_):
        assert c.delete(f'/v1/vehicles/{vid}', headers=h()).status_code == 204
        return vv.ProviderResult()
    monkeypatch.setattr(vv, 'fetch_valuation', delete_during_lookup)
    assert value(c, vid).status_code == 404
    with c.app.state.session_factory() as db:
        assert db.get(VehicleValuationCache, vid) is None


def test_uncertain_commit_never_reissues_reserved_or_completed_call(api):
    from sqlalchemy.orm import Session, sessionmaker
    c, calls = api
    vid = vehicle(c)
    fail = ['reservation']
    class LostAck(Session):
        def commit(self):
            cache = next((row for row in list(self.new) + list(self.dirty) if isinstance(row, VehicleValuationCache)), None)
            should_fail = bool(cache and fail and (
                (fail[0] == 'reservation' and cache.lease_token) or
                (fail[0] == 'completion' and not cache.lease_token)))
            super().commit()
            if should_fail:
                fail.clear()
                raise RuntimeError('Synthetic lost commit acknowledgment')
    original_factory = c.app.state.session_factory
    c.app.state.session_factory = sessionmaker(c.app.state.engine, class_=LostAck, expire_on_commit=False)
    try:
        with pytest.raises(RuntimeError, match='Synthetic lost commit'):
            value(c, vid)
        assert calls == [] and value(c, vid).json()['status'] == 'pending'
        with original_factory() as db:
            db.get(VehicleValuationCache, vid).lease_until = now() - timedelta(seconds=1)
            db.commit()
        fail.append('completion')
        with pytest.raises(RuntimeError, match='Synthetic lost commit'):
            value(c, vid)
        assert value(c, vid).json()['cached'] is True and len(calls) == 1
    finally:
        c.app.state.session_factory = original_factory


def test_invalid_vehicle_and_disabled_never_contact_provider(api):
    c, calls = api
    assert value(c, vehicle(c, vin='')).status_code == 422
    vid = vehicle(c)
    c.app.state.settings.valuation_enabled = False
    assert value(c, vid).json()['status'] == 'unavailable'
    c.app.state.settings.valuation_enabled = True
    c.app.state.settings.carsxe_api_key = ''
    assert value(c, vid).json()['status'] == 'unavailable'
    assert calls == []


def test_malformed_upstream_exception_is_sanitized(monkeypatch, caplog):
    import http.client
    def broken(*_, **__):
        raise http.client.BadStatusLine('private-query-key')
    monkeypatch.setattr(vv, '_fetch_https', broken)
    snapshot = {'vin': VIN, 'mileage': 50000, **BODY}
    assert vv.fetch_valuation(Settings(carsxe_api_key='private-key'), snapshot).payload is None
    assert 'private' not in caplog.text


@pytest.mark.parametrize('dialect', ['sqlite', 'postgresql'])
def test_migration_chain_and_private_table_boundary(dialect, tmp_path, monkeypatch):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    admin = schema = None
    if dialect == 'postgresql':
        supplied = os.getenv('PLUS_TEST_POSTGRES_URL')
        if not supplied:
            pytest.skip('PLUS_TEST_POSTGRES_URL required')
        url = make_url(supplied)
        if url.host not in {'localhost', '127.0.0.1'} or 'test' not in (url.database or ''):
            pytest.fail('Use a local disposable test database')
        admin = create_engine(url, isolation_level='AUTOCOMMIT')
        schema = 'plus_value_migrate_' + uuid4().hex
        with admin.connect() as db:
            db.execute(text(f'CREATE DATABASE "{schema}"'))
        database_url = url.set(database=schema).render_as_string(hide_password=False)
    else:
        database_url = f'sqlite:///{tmp_path / "migration.db"}'
    monkeypatch.setenv('DATABASE_URL', database_url)
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / 'alembic.ini'))
    config.set_main_option('script_location', str(backend / 'alembic'))
    engine = create_engine(database_url)
    try:
        command.upgrade(config, 'head')
        command.check(config)
        with engine.connect() as db:
            from estimoto_plus.app import EXPECTED_SCHEMA_REVISION
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == EXPECTED_SCHEMA_REVISION
            if dialect == 'postgresql':
                rows = db.execute(text("SELECT relname,relrowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname=:schema AND relname IN ('vehicle_valuation_cache','valuation_provider_state','vehicle_valuation_history')"), {'schema': 'public'}).all()
                assert len(rows) == 3 and all(enabled for _, enabled in rows)
        command.downgrade(config, 'd81a46bc720e')
        command.upgrade(config, 'head')
    finally:
        engine.dispose()
        if admin:
            with admin.connect() as db:
                db.execute(text(f'DROP DATABASE "{schema}"'))
            admin.dispose()
