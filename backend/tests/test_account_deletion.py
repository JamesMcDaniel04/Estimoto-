"""Account deletion removes everything the customer owns and nothing else."""
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from estimoto_plus.account import _paths
from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.models import Base, Customer, Estimate, Photo, Vehicle


def auth(who='alice'):
    return {'Authorization': f'Bearer {who}'}


@pytest.fixture
def stack(tmp_path):
    admin_calls = []

    def admin(request):
        admin_calls.append(request)
        return httpx.Response(204)

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'account.sqlite'}", environment='test', worker_enabled=False,
                        photo_dir=str(tmp_path / 'photos'), bridge_key='test', bridge_url='https://bridge.example.test/requests',
                        supabase_url='https://auth.example.test', supabase_publishable_key='pk', supabase_service_role_key='service-role')
    (tmp_path / 'photos').mkdir()
    app = create_app(settings, auth_verifier=lambda token: {'id': token, 'email': f'{token}@example.test', 'confirmed_at': 'ok'},
                     bridge_transport=httpx.MockTransport(lambda r: httpx.Response(202, json={'receipt_id': 'x'})))
    app.state.auth_admin_transport = httpx.MockTransport(admin)
    try:
        with TestClient(app) as client:
            yield client, app, admin_calls, tmp_path / 'photos'
    finally:
        app.state.engine.dispose()


def populate(client, who):
    client.put('/v1/profile', headers=auth(who), json={'name': who.title(), 'phone': '3035550123', 'postal_code': '80202'})
    vehicle = client.post('/v1/vehicles', headers=auth(who), json={'year': 2020, 'make': 'Ford', 'model': 'F-150', 'mileage': 1000}).json()['id']
    assert client.post('/v1/reminders', headers=auth(who), json={'vehicle_id': vehicle, 'title': 'Oil', 'due_date': '2030-01-01'}).status_code == 201
    assert client.post('/v1/knowledge/records', headers={**auth(who), 'Idempotency-Key': f'{who}-1'}, json={
        'vehicle_id': vehicle, 'service_type': 'repair', 'service_date': '2025-09-15', 'cost_cents': 100}).status_code == 201
    estimate = client.post('/v1/estimates', headers=auth(who), json={'vehicle_id': vehicle, 'discipline': 'pdr', 'description': 'Door ding'})
    assert estimate.status_code == 201, estimate.text
    return vehicle, estimate.json()['id']


def customer_rows(app, customer_id):
    rows = {}
    with app.state.session_factory() as db:
        for table, path in _paths().items():
            if table.name == 'customers':
                continue
            from estimoto_plus.account import _owned
            count = db.execute(select(table).where(_owned(path, customer_id))).all()
            if count:
                rows[table.name] = len(count)
        rows['customers'] = 1 if db.get(Customer, customer_id) else 0
    return rows


def test_every_customer_table_is_reachable_for_cleanup():
    reachable = {t.name for t in _paths()}
    expected = {'vehicles', 'estimates', 'photos', 'service_requests', 'outbox', 'reminders', 'my_shops', 'knowledge_records',
                'knowledge_receipts', 'customer_calendar_connections', 'customer_gmail_messages', 'rate_buckets', 'graph_edges'}
    assert expected <= reachable
    assert 'providers' not in reachable and 'public_directory_listings' not in reachable


def test_deletion_removes_only_the_requesting_customer(stack):
    client, app, admin_calls, photos = stack
    vehicle, estimate = populate(client, 'alice')
    populate(client, 'bob')
    # Private files referenced by rows that only the upload routes normally create.
    (photos / 'vehicle-images').mkdir()
    image, photo = '11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'
    (photos / 'vehicle-images' / image).write_bytes(b'img')
    (photos / photo).write_bytes(b'jpg')
    with app.state.session_factory() as db:
        db.get(Vehicle, vehicle).image_storage_name = image
        db.add(Photo(estimate_id=estimate, label='front', storage_name=photo, sha256='0' * 64, mime_type='image/jpeg', byte_size=3))
        db.commit()
    before = customer_rows(app, 'alice')
    assert before['vehicles'] == 1 and before['photos'] == 1 and before['knowledge_records'] == 1

    response = client.delete('/v1/account', headers=auth())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['deleted'] is True and body['identity_deleted'] is True
    assert body['removed']['vehicles'] == 1 and body['removed']['photos'] == 1
    assert customer_rows(app, 'alice') == {'customers': 0}
    assert customer_rows(app, 'bob')['vehicles'] == 1
    assert not (photos / 'vehicle-images' / image).exists() and not (photos / photo).exists()
    assert len(admin_calls) == 1
    call = admin_calls[0]
    assert call.method == 'DELETE' and call.url == 'https://auth.example.test/auth/v1/admin/users/alice'
    assert call.headers['apikey'] == 'service-role' and call.headers['Authorization'] == 'Bearer service-role'
    with app.state.session_factory() as db:
        assert db.execute(text('PRAGMA foreign_key_check')).all() == []
    # Bob is untouched and can keep working.
    assert client.get('/v1/bootstrap', headers=auth('bob')).json()['vehicles'][0]['make'] == 'Ford'


def test_identity_deletion_reports_failure_without_blocking_data_removal(stack):
    client, app, admin_calls, _ = stack
    populate(client, 'alice')
    app.state.auth_admin_transport = httpx.MockTransport(lambda r: httpx.Response(500, json={'msg': 'boom'}))
    body = client.delete('/v1/account', headers=auth()).json()
    assert body['deleted'] is True and body['identity_deleted'] is False
    assert customer_rows(app, 'alice') == {'customers': 0}


def test_unconfigured_service_role_leaves_identity_and_says_so(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'plain.sqlite'}", environment='test', worker_enabled=False,
                        photo_dir=str(tmp_path / 'photos'), bridge_key='test', bridge_url='https://bridge.example.test/requests')
    app = create_app(settings, auth_verifier=lambda token: {'id': token, 'email': f'{token}@example.test', 'confirmed_at': 'ok'})
    with TestClient(app) as client:
        populate(client, 'alice')
        assert client.delete('/v1/account').status_code == 401
        body = client.delete('/v1/account', headers=auth()).json()
        assert body['deleted'] is True and body['identity_deleted'] is None
    app.state.engine.dispose()


def test_demo_accounts_cannot_be_deleted(stack):
    client, app, _, _ = stack
    with app.state.session_factory() as db:
        db.add(Customer(id='demo-user', email='demo@example.test', demo=True))
        db.commit()
    assert client.delete('/v1/account', headers=auth('demo-user')).status_code == 403
