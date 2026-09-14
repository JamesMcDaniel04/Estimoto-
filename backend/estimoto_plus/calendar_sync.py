"""Durable, narrowly scoped calendar copies of explicitly checked appointments."""
from datetime import datetime, timedelta
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update

from .calendar_models import CalendarAttempt, CalendarConnection, CalendarOperation, CalendarProvision
from .calendar_provider import CalendarProvider, CalendarUnavailable, configured, instant
from .calendar_scheduling import booked_intervals, lock_customer, overlaps, utc
from .models import Customer, ServiceRequest, now, uid
from .shop_models import ShopOutreach
from .workflow import payload_hash

MODELS = {'request': ServiceRequest, 'outreach': ShopOutreach}
MESSAGES = {
    'pending': 'Calendar copy is pending.',
    'synced': None,
    'removed': None,
    'conflict': 'The confirmed appointment overlaps another commitment. Review the booking and retry Calendar sync.',
    'reconnect_required': 'Reconnect Google Calendar and retry this appointment to use your current preferences.',
    'attention_needed': 'Calendar needs review. Check the existing Estimoto + copy in Google Calendar before retrying.',
}


def source_start(source, kind):
    value = source.scheduled_at if kind == 'request' else source.confirmed_slot
    return utc(datetime.fromisoformat(value)) if isinstance(value, str) else utc(value)


def source_action(source, kind):
    if source.status in ('cancelled', 'declined'):
        return 'delete'
    if source.status == ('scheduled' if kind == 'request' else 'confirmed') and source_start(source, kind):
        return 'upsert'
    return None


def set_state(source, operation, state, message=None):
    if operation:
        operation.state = state
    source.calendar_sync_status = state
    source.calendar_sync_message = message if message else MESSAGES.get(state)


def event_payload(operation_id, event_id, source, kind):
    start = source_start(source, kind)
    if not start or not 30 <= source.duration_minutes <= 480:
        raise ValueError('Invalid appointment interval')
    # No customer contact, vehicle identity, notes, claim or insurance data is copied.
    title = 'Vehicle service appointment'
    payload = {'id': event_id, 'summary': title,
               'start': {'dateTime': start.isoformat()},
               'end': {'dateTime': (start + timedelta(minutes=source.duration_minutes)).isoformat()},
               'visibility': 'private', 'transparency': 'opaque', 'reminders': {'useDefault': False},
               'extendedProperties': {'private': {'estimotoPlusOperation': operation_id}}}
    return payload


def current_binding(row, source, settings):
    return bool(row and row.status == 'connected' and row.nango_connection_id and row.sync_confirmed and
                row.generation == source.calendar_generation and row.integration_id == settings.nango_calendar_integration_id and
                row.environment == settings.nango_environment and 1 <= len(row.selected_calendar_ids) <= 10)


def cleanup_binding(row, operation, settings):
    # Changed scheduling preferences must not strand a prior owned copy.
    return bool(row and operation and row.status == 'connected' and row.nango_connection_id and
                row.nango_connection_id == operation.nango_connection_id and
                row.integration_id == settings.nango_calendar_integration_id and row.environment == settings.nango_environment)


def _prepare(db, settings, kind, source_id):
    source = db.get(MODELS[kind], source_id)
    if not source:
        return None
    customer_id = source.customer_id
    db.rollback()
    lock_customer(db, customer_id)
    source = db.get(MODELS[kind], source_id)
    source.calendar_last_scan_at = now()
    customer, row = db.get(Customer, customer_id), db.get(CalendarConnection, customer_id)
    if not customer or customer.demo or not source.calendar_check or not source.calendar_sync_enabled:
        db.commit()
        return None
    operation = db.scalar(select(CalendarOperation).where(CalendarOperation.customer_id == customer_id,
                         CalendarOperation.source_kind == kind, CalendarOperation.source_id == source_id))
    action = source_action(source, kind)
    if action is None or action == 'delete' and operation is None:
        if action == 'delete':
            set_state(source, None, 'removed')
            db.commit()
        else:
            db.commit()
        return None
    cleanup = action == 'delete' and cleanup_binding(row, operation, settings)
    if not cleanup and not current_binding(row, source, settings):
        set_state(source, operation, 'reconnect_required')
        db.commit()
        return None
    if operation and operation.claim_token and operation.lease_until and utc(operation.lease_until) > now():
        db.commit()
        return None
    if operation and operation.state in ('attention_needed', 'conflict', 'reconnect_required') and not (
            cleanup and (operation.action != 'delete' or operation.state == 'reconnect_required')):
        db.commit()
        return None
    if not operation:
        operation_id = uid()
        operation = CalendarOperation(id=operation_id, customer_id=customer_id, source_kind=kind, source_id=source_id,
                                      generation=row.generation, nango_connection_id=row.nango_connection_id,
                                      event_id=UUID(operation_id).hex, payload={}, payload_hash='', attempts=0, next_attempt_at=now())
        db.add(operation)
    if not cleanup and (operation.generation != row.generation or operation.nango_connection_id != row.nango_connection_id):
        set_state(source, operation, 'reconnect_required')
        db.commit()
        return None
    # Recover a possibly completed earlier write before replacing its immutable payload.
    if operation.state != 'uncertain' or action == 'delete':
        try:
            desired = event_payload(operation.id, operation.event_id, source, kind) if action == 'upsert' else {}
        except (ValueError, TypeError):
            set_state(source, operation, 'attention_needed')
            db.commit()
            return None
        digest = payload_hash({'action': action, 'event': desired})
        if operation.payload_hash != digest:
            operation.payload, operation.payload_hash, operation.action = desired, digest, action
            operation.attempts, operation.next_attempt_at = 0, now()
            operation.state = 'pending'
        if operation.applied_hash == digest:
            set_state(source, operation, 'removed' if action == 'delete' else 'synced')
            db.commit()
            return None
    if utc(operation.next_attempt_at) > now():
        db.commit()
        return None
    if operation.attempts >= 6:
        set_state(source, operation, 'attention_needed')
        db.commit()
        return None
    claim = uid()
    operation.claim_token, operation.lease_until = claim, now() + timedelta(minutes=5)
    operation.attempts += 1
    operation.next_attempt_at = now() + timedelta(seconds=min(3600, 30 * 2 ** operation.attempts))
    set_state(source, None, 'pending')
    identifier = operation.id
    db.commit()
    return identifier, claim


def _provision(db, provider, row, operation, source):
    provision = db.scalar(select(CalendarProvision).where(CalendarProvision.customer_id == row.customer_id,
                          CalendarProvision.nango_connection_id == row.nango_connection_id))
    if not provision:
        provision = CalendarProvision(customer_id=row.customer_id, nango_connection_id=row.nango_connection_id, nonce=uid())
        db.add(provision)
        db.flush()
    if provision.status == 'ready' and provision.calendar_id:
        return provision.calendar_id
    if provision.status == 'attention_needed':
        set_state(source, operation, 'attention_needed', 'The app calendar creation outcome needs review. Open Google Calendar before retrying.')
        return None
    if provision.claim_token and provision.lease_until and utc(provision.lease_until) > now():
        return None
    nonce = 'estimoto-plus-calendar:' + provision.nonce
    if provision.status in ('creating', 'uncertain'):
        # No second POST after response loss, even when a complete list finds nothing.
        matches = [v for v in provider.calendars(row.nango_connection_id) if v.get('description') == nonce and v.get('accessRole') == 'owner']
        if len(matches) == 1:
            provision.calendar_id, provision.status = matches[0]['id'], 'ready'
            return provision.calendar_id
        provision.status = 'attention_needed'
        set_state(source, operation, 'attention_needed', 'The app calendar creation outcome is uncertain. Check Google Calendar before retrying.')
        return None
    provision.status, provision.claim_token, provision.lease_until = 'creating', operation.claim_token, now() + timedelta(minutes=5)
    # The claim survives a process crash or lost HTTP response before any provider mutation.
    generation, connection_id, customer_id = row.generation, row.nango_connection_id, row.customer_id
    db.commit()
    lock_customer(db, customer_id)
    row = db.get(CalendarConnection, customer_id)
    if row.generation != generation or row.nango_connection_id != connection_id or not row.sync_confirmed or row.status != 'connected':
        return None
    try:
        _, response = provider.call('POST', '/proxy/calendar/v3/calendars', connection=connection_id,
                                    body={'summary': 'Estimoto +', 'description': nonce, 'timeZone': row.time_zone})
        identifier = response.get('id')
        if not isinstance(identifier, str) or not 0 < len(identifier) <= 500 or response.get('description') != nonce:
            raise CalendarUnavailable()
        provision.calendar_id, provision.status = identifier, 'ready'
        return identifier
    except CalendarUnavailable as exc:
        provision.status = 'pending' if exc.status in (400, 401, 403, 404, 422) else 'uncertain'
        raise
    finally:
        provision.claim_token, provision.lease_until = None, None


def _owned_event(data, operation):
    private = (data.get('extendedProperties') or {}).get('private') if isinstance(data, dict) and isinstance(data.get('extendedProperties'), dict) else None
    return isinstance(private, dict) and data.get('id') == operation.event_id and private.get('estimotoPlusOperation') == operation.id


def _same_event(data, expected):
    try:
        return all(data.get(key) == expected[key] for key in ('id', 'summary', 'visibility', 'transparency', 'reminders', 'extendedProperties')) and all(
            instant(data[field]['dateTime']) == instant(expected[field]['dateTime']) for field in ('start', 'end')) and not data.get('attendees') and not data.get('conferenceData') and not data.get('description')
    except (KeyError, TypeError, CalendarUnavailable):
        return False


def _source_current(source, operation):
    action = source_action(source, operation.source_kind)
    try:
        desired = event_payload(operation.id, operation.event_id, source, operation.source_kind) if action == 'upsert' else {}
    except (TypeError, ValueError):
        return False
    return action == operation.action and payload_hash({'action': action, 'event': desired}) == operation.payload_hash


def _mark_applied(source, operation):
    operation.applied_hash = operation.payload_hash
    state = ('removed' if operation.action == 'delete' else 'synced') if _source_current(source, operation) else 'pending'
    set_state(source, operation, state)
    return state


def _source_lock(db, operation):
    model = MODELS[operation.source_kind]
    db.execute(update(model).where(model.id == operation.source_id).values(updated_at=model.updated_at))
    db.expire_all()
    return db.get(model, operation.source_id)


def _execute(db, settings, transport, identifier, claim):
    operation = db.get(CalendarOperation, identifier)
    if not operation:
        return 'skipped'
    customer_id = operation.customer_id
    db.rollback()
    lock_customer(db, customer_id)
    operation = db.get(CalendarOperation, identifier)
    source = _source_lock(db, operation)
    row = db.get(CalendarConnection, customer_id)
    if not source or operation.claim_token != claim or utc(operation.lease_until) <= now():
        db.rollback()
        return 'skipped'
    cleanup = operation.action == 'delete' and source_action(source, operation.source_kind) == 'delete' and cleanup_binding(row, operation, settings)
    if not cleanup and (not current_binding(row, source, settings) or operation.generation != row.generation or operation.nango_connection_id != row.nango_connection_id):
        set_state(source, operation, 'reconnect_required')
        operation.claim_token, operation.lease_until = None, None
        db.commit()
        return 'reconnect_required'
    provider = CalendarProvider(settings, transport)
    try:
        calendar_id = operation.calendar_id
        if not calendar_id:
            if operation.action == 'delete':
                provision = db.scalar(select(CalendarProvision).where(CalendarProvision.customer_id == customer_id,
                                     CalendarProvision.nango_connection_id == row.nango_connection_id))
                if not provision or provision.status == 'pending':
                    return _mark_applied(source, operation)  # No calendar creation was admitted.
            calendar_id = _provision(db, provider, row, operation, source)
            if not calendar_id:
                return operation.state
            operation.calendar_id = calendar_id
        path = '/proxy/calendar/v3/calendars/' + quote(calendar_id, safe='') + '/events'
        exact_path = path + '/' + operation.event_id
        code, existing = provider.call('GET', exact_path, connection=row.nango_connection_id, allow=(404, 410))
        exists = code == 200
        if operation.action == 'upsert' and (code == 410 or not exists and operation.applied_hash is not None):
            set_state(source, operation, 'attention_needed', 'The previous Calendar copy was deleted. Review it manually; automatic recreation is disabled.')
            return 'attention_needed'
        if exists and not _owned_event(existing, operation):
            set_state(source, operation, 'attention_needed')
            return 'attention_needed'
        if operation.action == 'delete':
            absence = code in (404, 410)
            if exists:
                # Delete only a copy carrying the exact operation's provenance.
                delete_code, _ = provider.call('DELETE', exact_path, connection=row.nango_connection_id, params={'sendUpdates': 'none'}, allow=(404, 410))
                absence = delete_code in (404, 410)
            if absence:
                # A proxy 404 can mean a vanished Nango binding, not an absent event.
                provider.verify_connection(row.nango_connection_id, customer_id, row.attempt_id)
                provision = db.scalar(select(CalendarProvision).where(CalendarProvision.customer_id == customer_id,
                                     CalendarProvision.nango_connection_id == row.nango_connection_id))
                if not provision or not any(v['id'] == calendar_id and v.get('accessRole') == 'owner' and
                        v.get('description') == 'estimoto-plus-calendar:' + provision.nonce
                        for v in provider.calendars(row.nango_connection_id)):
                    set_state(source, operation, 'attention_needed')
                    return 'attention_needed'
            return _mark_applied(source, operation)
        if exists and _same_event(existing, operation.payload):
            return _mark_applied(source, operation)
        if not _source_current(source, operation):
            set_state(source, operation, 'pending')
            operation.next_attempt_at = now()
            return 'pending'
        if existing and existing.get('status') == 'cancelled':
            set_state(source, operation, 'attention_needed')
            return 'attention_needed'
        start, end = instant(operation.payload['start']['dateTime']), instant(operation.payload['end']['dateTime'])
        if start <= now():
            set_state(source, operation, 'attention_needed', 'This appointment has already started. Review its Calendar copy manually.')
            return 'attention_needed'
        intervals = provider.freebusy(row.nango_connection_id, row.selected_calendar_ids, start, end)
        intervals += booked_intervals(db, customer_id, start, end, exclude=(operation.source_kind, operation.source_id))
        if overlaps(start, end, intervals):
            if exists and calendar_id in row.selected_calendar_ids:
                set_state(source, operation, 'attention_needed', 'The existing Calendar copy may overlap this new time. Adjust the existing copy or deselect the app calendar in preferences, then retry sync.')
            else:
                set_state(source, operation, 'conflict')
            return operation.state
        method, target = ('PUT', exact_path) if exists else ('POST', path)
        # Persist the exact operation before every mutation; the customer lock below
        # linearizes this outbound write with disconnect/preferences on every worker.
        operation.state = 'uncertain'
        generation, connection_id = row.generation, row.nango_connection_id
        db.commit()
        lock_customer(db, customer_id)
        operation = db.get(CalendarOperation, identifier)
        row = db.get(CalendarConnection, customer_id)
        source = _source_lock(db, operation)
        if not _source_current(source, operation):
            set_state(source, operation, 'pending')
            operation.next_attempt_at = now()
            return 'pending'
        if not current_binding(row, source, settings) or row.generation != generation or row.nango_connection_id != connection_id or operation.claim_token != claim:
            set_state(source, operation, 'reconnect_required')
            return 'reconnect_required'
        code, result = provider.call(method, target, connection=connection_id, params={'sendUpdates': 'none'}, body=operation.payload, allow=(409,))
        if code == 409:
            _, result = provider.call('GET', exact_path, connection=connection_id)
        if not _owned_event(result, operation) or not _same_event(result, operation.payload):
            set_state(source, operation, 'attention_needed')
            return 'attention_needed'
        return _mark_applied(source, operation)
    except CalendarUnavailable as exc:
        if exc.status in (401, 403):
            row.status, row.generation = 'reconnect_required', row.generation + 1
            set_state(source, operation, 'reconnect_required')
        else:
            # Preserve a provision's ambiguous result even if this was the first write.
            operation.state = 'uncertain'
            set_state(source, None, 'pending')
        return operation.state
    except (HTTPException, ValueError, TypeError, KeyError):
        set_state(source, operation, 'attention_needed')
        return 'attention_needed'
    finally:
        operation.claim_token, operation.lease_until = None, None
        db.commit()


def _revoke_batch(settings, factory, transport):
    with factory() as db:
        ids = db.scalars(select(CalendarAttempt.id).where(CalendarAttempt.revoke_pending.is_(True), CalendarAttempt.revoke_attempts < 6, CalendarAttempt.next_revoke_at <= now()).order_by(CalendarAttempt.next_revoke_at, CalendarAttempt.id).limit(20)).all()
    for identifier in ids:
        with factory() as db:
            attempt = db.get(CalendarAttempt, identifier)
            customer_id = attempt.customer_id
            db.rollback()
            lock_customer(db, customer_id)
            attempt = db.get(CalendarAttempt, identifier)
            if not attempt.revoke_pending or attempt.revoke_attempts >= 6:
                continue
            if attempt.integration_id != settings.nango_calendar_integration_id or attempt.environment != settings.nango_environment:
                continue
            attempt.revoke_attempts += 1
            attempt.next_revoke_at = now() + timedelta(minutes=2 ** attempt.revoke_attempts)
            provider = CalendarProvider(settings, transport)
            try:
                identifier = attempt.nango_connection_id or provider.reconcile(customer_id, attempt.id, require_usable=False)
                if identifier:
                    provider.revoke(identifier, customer_id, attempt.id)
                    attempt.revoke_pending = False
                elif utc(attempt.expires_at) < now():
                    attempt.revoke_pending = False
                else:
                    attempt.revoke_attempts -= 1
                    attempt.next_revoke_at = utc(attempt.expires_at) + timedelta(minutes=1)
            except CalendarUnavailable:
                pass
            db.commit()


def sync_calendar_batch(settings, session_factory, transport=None):
    counts = {'synced': 0, 'removed': 0, 'pending': 0, 'attention_needed': 0, 'conflict': 0, 'reconnect_required': 0, 'skipped': 0}
    if not configured(settings):
        return counts
    _revoke_batch(settings, session_factory, transport)
    with session_factory() as db:
        sources = [(kind, identifier) for kind, model in MODELS.items() for identifier in db.scalars(
            select(model.id).where(model.calendar_check.is_(True), model.calendar_sync_enabled.is_(True),
                                   model.status.in_(('scheduled', 'confirmed', 'cancelled', 'declined')))
            .order_by(model.calendar_last_scan_at.is_not(None), model.calendar_last_scan_at, model.id).limit(100)).all()]
    for kind, source_id in sources:
        with session_factory() as db:
            claim = _prepare(db, settings, kind, source_id)
        if not claim:
            counts['skipped'] += 1
            continue
        with session_factory() as db:
            result = _execute(db, settings, transport, *claim)
            counts[result if result in counts else 'pending'] += 1
    return counts
