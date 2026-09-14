"""Checked choices preserve request replay and recheck the whole reservation."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from test_customer_calendar import auth, calendar, connect, select_calendar, window
from estimoto_plus.calendar_scheduling import candidates
from estimoto_plus.models import Provider, ServiceRequest
from estimoto_plus.workflow import payload_hash


def test_full_duration_overlap_and_endpoint_touching():
    start = datetime(2026, 9, 14, 15, tzinfo=timezone.utc)  # Monday 09:00 Denver
    end = datetime(2026, 9, 14, 18, tzinfo=timezone.utc)
    busy = [(datetime(2026, 9, 14, 15, 45, tzinfo=timezone.utc), datetime(2026, 9, 14, 16, 30, tzinfo=timezone.utc))]
    rows = candidates(start, end, 60, 'America/Denver', 9, 12, busy)
    assert [r['start'] for r in rows] == ['2026-09-14T16:30:00+00:00', '2026-09-14T17:00:00+00:00']


@pytest.mark.parametrize('timestamp', ['9999-12-31T23:59:59+00:00', '9999-12-31T23:59:59-07:00', '0001-01-01T00:00:00+07:00'])
def test_extreme_checked_timestamp_is_definite_rejection(calendar, timestamp):
    client, app = calendar
    connect(client, app)
    state = select_calendar(client)
    body = request_body(client, app)
    body.update(calendar_check=True, calendar_generation=state['generation'],
                proposed_slots=[timestamp], duration_minutes=60)
    headers = {**auth(), 'Idempotency-Key': 'extreme-date'}
    response = client.post('/v1/requests', headers=headers, json=body)
    assert response.status_code == 422
    assert client.post('/v1/requests', headers=headers, json=body).json() == response.json()


def test_dst_weekend_skipped_and_business_hours_use_changed_offset():
    start = datetime(2026, 10, 30, 14, tzinfo=timezone.utc)
    end = datetime(2026, 11, 3, 19, tzinfo=timezone.utc)
    rows = candidates(start, end, 480, 'America/Denver', 9, 17, [])
    assert [r['start'] for r in rows] == ['2026-10-30T15:00:00+00:00', '2026-11-02T16:00:00+00:00']
    assert [r['end'] for r in rows] == ['2026-10-30T23:00:00+00:00', '2026-11-03T00:00:00+00:00']


def request_body(client, app):
    with app.state.session_factory() as db:
        db.add(Provider(id='shop', source_id='trusted-shop', name='Test Shop', kind='shop', specialties=['maintenance'],
                        postal_codes=['80202'], accepting_requests=True, public_visible=True, demo_only=False))
        db.commit()
    vehicle = client.post('/v1/vehicles', headers=auth(), json={'year': 2020, 'make': 'Toyota', 'model': 'Camry'}).json()['id']
    return {'vehicle_id': vehicle, 'provider_id': 'shop', 'specialty': 'maintenance', 'description': 'Inspect a noise',
            'preferred_time': '', 'share_contact': True}


def test_old_request_body_replays_exact_legacy_digest(calendar):
    client, app = calendar
    body = request_body(client, app)
    response = client.post('/v1/requests', headers={**auth(), 'Idempotency-Key': 'legacy'}, json=body)
    assert response.status_code == 201, response.text
    with app.state.session_factory() as db:
        assert db.query(ServiceRequest).one().payload_hash == payload_hash(body)
    assert client.post('/v1/requests', headers={**auth(), 'Idempotency-Key': 'legacy'}, json=body).json()['id'] == response.json()['id']


def test_checked_request_freezes_private_slots_and_tombstones_definite_conflict(calendar):
    client, app = calendar
    stub, _ = connect(client, app)
    state = select_calendar(client, True)
    body = request_body(client, app)
    slot = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    body.update(calendar_check=True, duration_minutes=90, calendar_generation=state['generation'], proposed_slots=[slot.isoformat()])
    response = client.post('/v1/requests', headers={**auth(), 'Idempotency-Key': 'checked'}, json=body)
    assert response.status_code == 201, response.text
    assert response.json()['calendar_check'] is True
    assert response.json()['calendar_time_zone'] == 'America/Denver'
    assert '90 min' in response.json()['preferred_time']
    # Previously accepted replay is authoritative even after disconnect.
    assert client.delete('/v1/calendar/google/connection', headers=auth()).status_code == 200
    replay = client.post('/v1/requests', headers={**auth(), 'Idempotency-Key': 'checked'}, json=body)
    assert replay.json()['id'] == response.json()['id']
    rejected = client.post('/v1/requests', headers={**auth(), 'Idempotency-Key': 'stale'}, json=body)
    assert rejected.status_code == 422
    assert rejected.json()['code'] == 'request_not_created'
    with app.state.session_factory() as db:
        assert db.query(ServiceRequest).count() == 1


def test_outreach_rechecks_busy_at_authorization_and_preserves_old_review(calendar):
    client, app = calendar
    stub, _ = connect(client, app)
    state = select_calendar(client)
    shop = client.post('/v1/my-shops', headers=auth(), json={'name': 'Private Garage', 'phone': '3035550123', 'email': '', 'address': ''}).json()['id']
    slot = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    body = {'shop_id': shop, 'vehicle_id': None, 'service_summary': 'Inspection', 'customer_message': '', 'proposed_slots': [slot.isoformat()],
            'calendar_check': True, 'duration_minutes': 120, 'calendar_generation': state['generation']}
    draft = client.post('/v1/shop-outreach', headers={**auth(), 'Idempotency-Key': 'draft'}, json=body)
    assert draft.status_code == 201, draft.text
    stub.busy = [{'start': (slot + timedelta(minutes=90)).isoformat(), 'end': (slot + timedelta(minutes=100)).isoformat()}]
    response = client.post('/v1/shop-outreach/' + draft.json()['id'] + '/authorize', headers={**auth(), 'Idempotency-Key': 'authorize'},
                           json={'share_contact': True, 'review_hash': draft.json()['review_hash']})
    assert response.status_code == 422
    assert client.get('/v1/shop-outreach/' + draft.json()['id'], headers=auth()).json()['status'] == 'draft'


def test_all_day_busy_and_saved_booking_block_proposals(calendar):
    client, app = calendar
    stub, _ = connect(client, app)
    select_calendar(client)
    body = window()
    stub.busy = [{'start': body['time_min'], 'end': body['time_max']}]
    response = client.post('/v1/calendar/google/availability', headers=auth(), json=body)
    assert response.status_code == 200 and response.json()['slots'] == []
    stub.busy = []
    initial = client.post('/v1/calendar/google/availability', headers=auth(), json=body).json()['slots'][0]
    req = request_body(client, app)
    record = client.post('/v1/requests', headers={**auth(), 'Idempotency-Key': 'legacy-booking'}, json=req).json()
    with app.state.session_factory() as db:
        row = db.get(ServiceRequest, record['id'])
        row.status = 'scheduled'
        row.scheduled_at = datetime.fromisoformat(initial['start'])
        db.commit()
    remaining = client.post('/v1/calendar/google/availability', headers=auth(), json=body).json()['slots']
    assert initial not in remaining


def test_outreach_worker_and_shop_confirmation_recheck_calendar(calendar, monkeypatch):
    import asyncio
    import httpx
    import re
    from estimoto_plus import saved_shops
    from estimoto_plus.saved_shops import deliver_shop_batch
    client, app = calendar
    monkeypatch.setenv('RESEND_API_KEY', 'synthetic-mail')
    monkeypatch.setenv('EMAIL_FROM', 'Plus <hello@example.test>')
    monkeypatch.setenv('SHOP_ACTION_BASE_URL', 'https://plus.example.test')
    sent = []
    app.state.shop_mail_transport = httpx.MockTransport(lambda r: (sent.append(r), httpx.Response(200, json={'id': 'mail'}))[1])
    stub, _ = connect(client, app)
    state = select_calendar(client)
    shop = client.post('/v1/my-shops', headers=auth(), json={'name': 'Garage', 'email': 'shop@example.test', 'phone': '', 'address': ''}).json()['id']
    start = datetime.now(timezone.utc) + timedelta(days=2)
    body = {'shop_id': shop, 'service_summary': 'Inspection', 'proposed_slots': [start.isoformat()],
            'calendar_check': True, 'duration_minutes': 60, 'calendar_generation': state['generation']}
    def draft_and_authorize(key):
        draft = client.post('/v1/shop-outreach', headers={**auth(), 'Idempotency-Key': key}, json=body).json()
        assert client.post('/v1/shop-outreach/' + draft['id'] + '/authorize', headers={**auth(), 'Idempotency-Key': key},
                           json={'share_contact': True, 'review_hash': draft['review_hash']}).status_code == 200
        return draft
    first = draft_and_authorize('first')
    stub.busy = [{'start': start.isoformat(), 'end': (start + timedelta(minutes=30)).isoformat()}]
    result = deliver_shop_batch(app.state.session_factory, app.state.shop_mail_transport,
                               calendar_settings=app.state.settings, calendar_transport=app.state.calendar_transport)
    assert result['failed'] == 1 and sent == []
    stub.busy = []
    second = draft_and_authorize('second')
    assert deliver_shop_batch(app.state.session_factory, app.state.shop_mail_transport,
                               calendar_settings=app.state.settings, calendar_transport=app.state.calendar_transport)['delivered'] == 1
    path = re.search(r'/v1/shop-actions/[A-Za-z0-9_-]+', sent[0].read().decode()).group(0)
    original_check = saved_shops.check_slots
    def off_event_loop(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return original_check(*args, **kwargs)
        raise AssertionError('Blocking Calendar admission must run outside the event loop')
    monkeypatch.setattr(saved_shops, 'check_slots', off_event_loop)
    stub.busy = [{'start': start.isoformat(), 'end': (start + timedelta(minutes=30)).isoformat()}]
    assert client.post(path, data={'slot': second['proposed_slots'][0]}).status_code == 422
    assert client.get('/v1/shop-outreach/' + second['id'], headers=auth()).json()['status'] == 'waiting_for_reply'
    stub.busy = []
    assert client.post(path, data={'slot': second['proposed_slots'][0]}).status_code == 200
    # Exact confirmation replay does not attempt a second admission after the source itself blocks time.
    assert client.post(path, data={'slot': second['proposed_slots'][0]}).status_code == 200


def test_changed_preferences_invalidate_unaccepted_checked_review(calendar):
    client, app = calendar
    _, _ = connect(client, app)
    state = select_calendar(client)
    shop = client.post('/v1/my-shops', headers=auth(), json={'name': 'Garage', 'email': '', 'phone': '3035550123', 'address': ''}).json()['id']
    body = {'shop_id': shop, 'service_summary': 'Inspection', 'proposed_slots': [(datetime.now(timezone.utc) + timedelta(days=2)).isoformat()],
            'calendar_check': True, 'calendar_generation': state['generation']}
    reviewed = client.post('/v1/shop-outreach', headers={**auth(), 'Idempotency-Key': 'stale-review'}, json=body).json()
    assert client.put('/v1/calendar/google/preferences', headers=auth(), json={
        'selected_calendar_ids': ['primary@example.test'], 'time_zone': 'America/New_York', 'sync_confirmed': False}).status_code == 200
    assert client.post('/v1/shop-outreach/' + reviewed['id'] + '/authorize', headers={**auth(), 'Idempotency-Key': 'stale-auth'},
                       json={'share_contact': True, 'review_hash': reviewed['review_hash']}).status_code == 422
