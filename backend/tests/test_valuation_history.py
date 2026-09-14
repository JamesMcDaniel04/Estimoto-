"""Private per-vehicle valuation history."""
from test_vehicle_valuation import BODY, api, h, value, vehicle  # noqa: F401  (fixture reuse)


def test_valuation_lookups_are_kept_per_vehicle_and_deletable(api):
    c, calls = api
    vid = vehicle(c)
    first = value(c, vid)
    assert first.status_code == 200 and first.json()['status'] == 'available'
    second = value(c, vid)
    assert second.json()['cached'] is True
    listed = c.get(f'/v1/vehicles/{vid}/valuations', headers=h())
    assert listed.status_code == 200 and listed.headers['cache-control'] == 'private, no-store'
    rows = listed.json()['valuations']
    assert len(rows) == 2 and rows[0]['created_at'] >= rows[1]['created_at']
    assert rows[0]['state'] == 'CO' and rows[0]['condition'] == 'clean' and rows[0]['mileage'] == 50000
    assert rows[0]['payload']['buckets'][0]['amount_cents'] == 920000
    assert c.get(f'/v1/vehicles/{vid}/valuations', headers=h('bob')).status_code == 404
    assert c.delete(f"/v1/vehicles/{vid}/valuations/{rows[0]['id']}", headers=h('bob')).status_code == 404
    assert c.delete(f"/v1/vehicles/{vid}/valuations/{rows[0]['id']}", headers=h()).status_code == 204
    assert c.delete(f"/v1/vehicles/{vid}/valuations/{rows[0]['id']}", headers=h()).status_code == 404
    assert len(c.get(f'/v1/vehicles/{vid}/valuations', headers=h()).json()['valuations']) == 1
    # Deleting the vehicle removes its history too.
    assert c.delete(f'/v1/vehicles/{vid}', headers=h()).status_code == 204
    assert c.get(f'/v1/vehicles/{vid}/valuations', headers=h()).status_code == 404


def test_valuation_history_is_capped_at_fifty(api):
    c, calls = api
    vid = vehicle(c)
    from estimoto_plus.valuation_models import VehicleValuationHistory
    with c.app.state.session_factory() as db:
        for i in range(55):
            db.add(VehicleValuationHistory(customer_id='alice', vehicle_id=vid, state='CO', condition='clean',
                                           mileage=1000 + i, input_hash='x' * 64, payload={'buckets': []}))
        db.commit()
    assert value(c, vid).status_code == 200
    assert len(c.get(f'/v1/vehicles/{vid}/valuations', headers=h()).json()['valuations']) == 50


def test_readiness_accepts_migrated_schema(api):
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text
    c, _ = api
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / 'alembic.ini'))
    cfg.set_main_option('script_location', str(backend / 'alembic'))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with c.app.state.engine.begin() as db:
        db.execute(text('CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)'))
        db.execute(text('DELETE FROM alembic_version'))
        db.execute(text('INSERT INTO alembic_version(version_num) VALUES (:head)'), {'head': head})
    Path(c.app.state.settings.photo_dir).mkdir(parents=True, exist_ok=True)
    response = c.get('/ready')
    assert response.status_code == 200, response.text
    assert response.json()['schema_revision'] == head
