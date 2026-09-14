"""Durable calendar copies reconcile uncertain outcomes and keep booking authority private."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import httpx

from test_customer_calendar import auth, calendar, connect, select_calendar
from test_calendar_scheduling import request_body
from estimoto_plus.models import ServiceRequest, now


def scheduled(client, app):
    stub, _ = connect(client, app)
    state = select_calendar(client, True)
    body = request_body(client, app)
    stamp = (now() + timedelta(days=2)).replace(microsecond=0)
    body.update(calendar_check=True, calendar_generation=state['generation'], duration_minutes=60, proposed_slots=[stamp.isoformat()])
    result = client.post('/v1/requests', headers={**auth(), 'Idempotency-Key': 'sync'}, json=body)
    assert result.status_code == 201, result.text
    with app.state.session_factory() as db:
        row = db.get(ServiceRequest, result.json()['id'])
        row.status, row.scheduled_at = 'scheduled', stamp
        db.commit()
    return stub, result.json()['id'], stamp


class CalendarWrites:
    def __init__(self, stub):
        self.stub = stub
        self.events = {}
        self.calendar_posts = 0
        self.event_posts = 0
        self.puts = 0
        self.deletes = 0
        self.lose_calendar = False
        self.lose_event = False
        self.lose_without_event = False
        stub.on_request = self

    def __call__(self, request):
        path = request.url.path
        if path == '/proxy/calendar/v3/calendars' and request.method == 'POST':
            self.calendar_posts += 1
            payload = json.loads(request.content)
            self.stub.calendars.append({'id': 'app-calendar', **payload, 'accessRole': 'owner', 'primary': False})
            if self.lose_calendar:
                self.lose_calendar = False
                raise httpx.ReadTimeout('synthetic response loss', request=request)
            return httpx.Response(200, json={'id': 'app-calendar', **payload})
        if path.startswith('/proxy/calendar/v3/calendars/app-calendar/events'):
            assert request.headers['Retries'] == '0'
            if request.method == 'POST':
                self.event_posts += 1
                payload = json.loads(request.content)
                assert payload['visibility'] == 'private' and payload['transparency'] == 'opaque'
                assert payload['reminders'] == {'useDefault': False}
                assert 'attendees' not in payload and 'description' not in payload and 'conferenceData' not in payload
                assert request.url.params['sendUpdates'] == 'none'
                if not self.lose_without_event:
                    self.events[payload['id']] = payload
                if self.lose_event or self.lose_without_event:
                    self.lose_event = False
                    raise httpx.ReadTimeout('synthetic response loss', request=request)
                return httpx.Response(200, json=payload)
            identifier = path.split('/')[-1]
            if request.method == 'GET':
                return httpx.Response(200 if identifier in self.events else 404, json=self.events.get(identifier, {}))
            if request.method == 'PUT':
                self.puts += 1
                self.events[identifier] = json.loads(request.content)
                return httpx.Response(200, json=self.events[identifier])
            if request.method == 'DELETE':
                self.deletes += 1
                self.events.pop(identifier, None)
                return httpx.Response(204)
        return None


def batch(app):
    from estimoto_plus.calendar_sync import sync_calendar_batch
    return sync_calendar_batch(app.state.settings, app.state.session_factory, app.state.calendar_transport)


def due(app):
    from estimoto_plus.calendar_models import CalendarOperation, CalendarProvision
    with app.state.session_factory() as db:
        for row in db.query(CalendarOperation).all():
            row.next_attempt_at = now()
            row.lease_until = now() - timedelta(seconds=1)
        for row in db.query(CalendarProvision).all():
            row.lease_until = now() - timedelta(seconds=1)
        db.commit()


def test_calendar_creation_and_event_response_loss_reconcile_without_duplicates(calendar):
    client, app = calendar
    stub, identifier, _ = scheduled(client, app)
    writes = CalendarWrites(stub)
    writes.lose_calendar = True
    batch(app)
    due(app)
    writes.lose_event = True
    batch(app)
    due(app)
    batch(app)
    assert writes.calendar_posts == 1
    assert writes.event_posts == 1
    state = client.get('/v1/requests', headers=auth()).json()[0]
    assert state['calendar_sync_status'] == 'synced'
    assert state['status'] == 'scheduled'


def test_two_workers_reschedule_same_event_and_cancel_only_that_event(calendar):
    client, app = calendar
    stub, identifier, stamp = scheduled(client, app)
    writes = CalendarWrites(stub)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: batch(app), range(2)))
    assert writes.calendar_posts == 1 and writes.event_posts == 1
    event_id = next(iter(writes.events))
    with app.state.session_factory() as db:
        db.get(ServiceRequest, identifier).scheduled_at = stamp + timedelta(hours=2)
        db.commit()
    batch(app)
    assert writes.puts == 1
    assert next(iter(writes.events)) == event_id
    assert writes.events[event_id]['start']['dateTime'] == (stamp + timedelta(hours=2)).isoformat()
    with app.state.session_factory() as db:
        db.get(ServiceRequest, identifier).status = 'cancelled'
        db.commit()
    batch(app)
    assert writes.deletes == 1 and not writes.events
    assert client.get('/v1/requests', headers=auth()).json()[0]['calendar_sync_status'] == 'removed'


def test_unrelated_event_id_collision_is_never_overwritten(calendar):
    from estimoto_plus.calendar_models import CalendarOperation
    client, app = calendar
    stub, identifier, _ = scheduled(client, app)
    writes = CalendarWrites(stub)
    writes.lose_without_event = True
    batch(app)
    with app.state.session_factory() as db:
        operation = db.query(CalendarOperation).one()
        event_id = operation.event_id
    writes.events[event_id] = {'id': event_id, 'summary': 'Unrelated private title', 'extendedProperties': {'private': {'estimotoPlusOperation': 'someone-else'}}}
    due(app)
    batch(app)
    assert writes.puts == 0 and writes.deletes == 0
    state = client.get('/v1/requests', headers=auth()).json()[0]
    assert state['calendar_sync_status'] == 'attention_needed'
    assert 'Unrelated private title' not in json.dumps(state)


def test_disconnect_stops_new_copies_and_legacy_bookings_are_not_imported(calendar):
    client, app = calendar
    stub, identifier, _ = scheduled(client, app)
    writes = CalendarWrites(stub)
    assert client.delete('/v1/calendar/google/connection', headers=auth()).status_code == 200
    batch(app)
    assert writes.calendar_posts == 0 and writes.event_posts == 0
    assert client.get('/v1/requests', headers=auth()).json()[0]['status'] == 'scheduled'


def test_authenticated_bridge_reschedule_reuses_event_and_preserves_terminal_guard(calendar):
    client, app = calendar
    stub, identifier, stamp = scheduled(client, app)
    writes = CalendarWrites(stub)
    with app.state.session_factory() as db:
        row = db.get(ServiceRequest, identifier)
        row.status, row.delivery_status, row.scheduled_at = 'requested', 'delivered', None
        db.commit()
    path = '/v1/bridge/requests/' + identifier + '/events'
    headers = {'X-Bridge-Key': 'test'}
    event = {'event_id': 'accept', 'provider_id': 'shop', 'status': 'accepted', 'message': ''}
    assert client.post(path, headers=headers, json=event).status_code == 200
    event.update(event_id='initial', status='scheduled', scheduled_at=stamp.isoformat())
    assert client.post(path, headers=headers, json=event).status_code == 200
    batch(app)
    event_id = next(iter(writes.events))
    event.update(event_id='reschedule', scheduled_at=(stamp + timedelta(hours=2)).isoformat())
    assert client.post(path, headers=headers, json=event).status_code == 200
    batch(app)
    assert next(iter(writes.events)) == event_id and writes.event_posts == 1 and writes.puts == 1
    assert client.post(path, headers=headers, json=event).status_code == 200
    assert client.post(path, headers=headers, json={**event, 'scheduled_at': (stamp + timedelta(hours=3)).isoformat()}).status_code == 409
    assert client.post(path, headers=headers, json={'event_id': 'cancel', 'provider_id': 'shop', 'status': 'cancelled', 'message': ''}).status_code == 200
    assert client.post(path, headers=headers, json={**event, 'event_id': 'after-cancel'}).status_code == 409


def test_single_booking_retry_rechecks_conflict_and_is_customer_owned(calendar):
    client, app = calendar
    stub, identifier, stamp = scheduled(client, app)
    writes = CalendarWrites(stub)
    stub.busy = [{'start': stamp.isoformat(), 'end': (stamp + timedelta(minutes=30)).isoformat()}]
    batch(app)
    state = client.get('/v1/requests', headers=auth()).json()[0]
    assert state['calendar_sync_status'] == 'conflict' and state['status'] == 'scheduled'
    body = {'source_kind': 'request', 'source_id': identifier}
    assert client.post('/v1/calendar/google/sync/retry', headers=auth('bob'), json=body).status_code == 404
    assert client.post('/v1/calendar/google/sync/retry', headers=auth(), json=body).status_code == 422
    stub.busy = []
    response = client.post('/v1/calendar/google/sync/retry', headers=auth(), json=body)
    assert response.status_code == 200, response.text
    assert response.json()['calendar_sync_status'] == 'pending'
    batch(app)
    assert writes.event_posts == 1
    assert client.get('/v1/requests', headers=auth()).json()[0]['calendar_sync_status'] == 'synced'


def test_cancel_after_uncertain_event_does_not_create_delayed_copy(calendar):
    client, app = calendar
    stub, identifier, _ = scheduled(client, app)
    writes = CalendarWrites(stub)
    writes.lose_without_event = True
    batch(app)
    assert writes.event_posts == 1
    with app.state.session_factory() as db:
        db.get(ServiceRequest, identifier).status = 'cancelled'
        db.commit()
    due(app)
    batch(app)
    due(app)
    batch(app)
    assert writes.event_posts == 1
    assert client.get('/v1/requests', headers=auth()).json()[0]['calendar_sync_status'] == 'removed'


def test_fair_scan_reaches_older_source_beyond_first_hundred(calendar):
    client, app = calendar
    stub, identifier, stamp = scheduled(client, app)
    writes = CalendarWrites(stub)
    with app.state.session_factory() as db:
        original = db.get(ServiceRequest, identifier)
        original.updated_at = now() - timedelta(days=1)
        for index in range(110):
            db.add(ServiceRequest(customer_id=original.customer_id, vehicle_id=original.vehicle_id, provider_id=original.provider_id,
                specialty='maintenance', description='Synthetic terminal request', status='cancelled', delivery_status='delivered',
                idempotency_key=f'fair-{index}', payload_hash='0'*64, calendar_check=True, calendar_sync_enabled=True,
                calendar_generation=original.calendar_generation, calendar_selected_ids=original.calendar_selected_ids,
                calendar_time_zone=original.calendar_time_zone, updated_at=now()))
        db.commit()
    batch(app)
    batch(app)
    with app.state.session_factory() as db:
        assert db.get(ServiceRequest, identifier).calendar_sync_status == 'synced'
        assert db.get(ServiceRequest, identifier).updated_at.replace(tzinfo=timezone.utc) < now() - timedelta(hours=23)
    assert writes.event_posts == 1


def test_reconnect_adopts_only_verified_existing_calendar_without_cloning(calendar):
    from estimoto_plus.calendar_models import CalendarConnection, CalendarAttempt
    client, app = calendar
    stub, identifier, _ = scheduled(client, app)
    writes = CalendarWrites(stub)
    batch(app)
    event_id = next(iter(writes.events))
    # Synthetic reauthorization has a different Nango connection, same Google calendar.
    with app.state.session_factory() as db:
        row = db.get(CalendarConnection, 'alice')
        row.generation += 1
        row.nango_connection_id = 'reconnected'
        db.commit()
    stub.on_request = lambda r: (httpx.Response(200, json={'items': stub.calendars}) if r.url.path.endswith('/calendarList') else
                                httpx.Response(200, json={'timeMin': json.loads(r.content)['timeMin'], 'timeMax': json.loads(r.content)['timeMax'],
                                    'calendars': {'primary@example.test': {'busy': []}}}) if r.url.path.endswith('/freeBusy') else writes(r))
    response = client.post('/v1/calendar/google/sync/retry', headers=auth(), json={'source_kind': 'request', 'source_id': identifier})
    assert response.status_code == 200, response.text
    batch(app)
    assert writes.calendar_posts == 1 and writes.event_posts == 1
    assert next(iter(writes.events)) == event_id


def test_reconnect_to_other_google_account_cannot_clone_old_copy(calendar):
    from estimoto_plus.calendar_models import CalendarConnection
    client, app = calendar
    stub, identifier, _ = scheduled(client, app)
    writes = CalendarWrites(stub)
    batch(app)
    with app.state.session_factory() as db:
        row = db.get(CalendarConnection, 'alice')
        row.generation += 1
        row.nango_connection_id = 'different-google-account'
        db.commit()
    stub.on_request = lambda r: httpx.Response(200, json={'items': []}) if r.url.path.endswith('/calendarList') else writes(r)
    response = client.post('/v1/calendar/google/sync/retry', headers=auth(), json={'source_kind': 'request', 'source_id': identifier})
    assert response.status_code == 422, response.text
    assert writes.calendar_posts == 1 and writes.event_posts == 1


def test_selected_app_calendar_reschedule_is_conservative_and_retry_keeps_id(calendar):
    from estimoto_plus.calendar_models import CalendarConnection
    client, app = calendar
    stub, identifier, stamp = scheduled(client, app)
    writes = CalendarWrites(stub)
    batch(app)
    event_id = next(iter(writes.events))
    with app.state.session_factory() as db:
        row = db.get(CalendarConnection, 'alice')
        row.selected_calendar_ids = ['app-calendar', 'primary@example.test']
        source = db.get(ServiceRequest, identifier)
        source.calendar_selected_ids = list(row.selected_calendar_ids)
        source.scheduled_at = stamp + timedelta(minutes=30)
        db.commit()
    def selected_busy(request):
        if request.url.path.endswith('/freeBusy'):
            body = json.loads(request.content)
            return httpx.Response(200, json={'timeMin': body['timeMin'], 'timeMax': body['timeMax'],
                'calendars': {value['id']: {'busy': [{'start': stamp.isoformat(), 'end': (stamp + timedelta(hours=1)).isoformat()}]
                                             if value['id'] == 'app-calendar' else []} for value in body['items']}})
        return writes(request)
    stub.on_request = selected_busy
    batch(app)
    assert writes.puts == 0 and writes.deletes == 0
    assert client.get('/v1/requests', headers=auth()).json()[0]['calendar_sync_status'] == 'attention_needed'
    select_calendar(client, True)  # Customer deselects app calendar; private DB still blocks other bookings.
    response = client.post('/v1/calendar/google/sync/retry', headers=auth(), json={'source_kind': 'request', 'source_id': identifier})
    assert response.status_code == 200, response.text
    batch(app)
    assert writes.puts == 1 and writes.event_posts == 1 and next(iter(writes.events)) == event_id


def test_definite_missing_write_scope_can_recover_without_uncertain_calendar_clone(calendar):
    from estimoto_plus.calendar_models import CalendarConnection
    client, app = calendar
    stub, identifier, _ = scheduled(client, app)
    writes = CalendarWrites(stub)
    stub.on_request = lambda r: httpx.Response(403, json={'error': 'insufficient scope'}) if r.url.path == '/proxy/calendar/v3/calendars' else writes(r)
    batch(app)
    assert writes.calendar_posts == 0
    with app.state.session_factory() as db:
        row = db.get(CalendarConnection, 'alice')
        assert row.status == 'reconnect_required'
        row.status, row.nango_connection_id = 'connected', 'new-grant'
        db.commit()
    def repaired(request):
        if request.url.path.endswith('/freeBusy'):
            body = json.loads(request.content)
            return httpx.Response(200, json={'timeMin': body['timeMin'], 'timeMax': body['timeMax'],
                                            'calendars': {'primary@example.test': {'busy': []}}})
        return writes(request)
    stub.on_request = repaired
    assert client.post('/v1/calendar/google/sync/retry', headers=auth(), json={'source_kind': 'request', 'source_id': identifier}).status_code == 200
    batch(app)
    assert writes.calendar_posts == 1 and writes.event_posts == 1


def test_intentionally_deleted_known_event_is_not_recreated(calendar):
    client, app = calendar
    stub, identifier, stamp = scheduled(client, app)
    writes = CalendarWrites(stub)
    batch(app)
    writes.events.clear()
    with app.state.session_factory() as db:
        db.get(ServiceRequest, identifier).scheduled_at = stamp + timedelta(hours=2)
        db.commit()
    batch(app)
    assert writes.event_posts == 1 and writes.puts == 0
    assert client.get('/v1/requests', headers=auth()).json()[0]['calendar_sync_status'] == 'attention_needed'
