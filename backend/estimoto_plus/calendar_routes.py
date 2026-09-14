"""Verified customer-only Calendar setup and availability endpoints."""
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_customer, db_session
from .calendar_models import CalendarAttempt, CalendarConnection, CalendarOperation
from .calendar_provider import CalendarProvider, CalendarUnavailable, configured
from .calendar_scheduling import AvailabilityWrite, binding, booked_intervals, candidates, consume_rate, lock_customer, unchanged, utc, zone, provider_failure, check_slots
from .models import Customer, now, uid

router = APIRouter(prefix='/v1/calendar/google', tags=['customer calendar'])


class ReconcileWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    attempt_id: str = Field(min_length=36, max_length=36)


class PreferencesWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    selected_calendar_ids: list[str] = Field(min_length=1, max_length=10)
    time_zone: str = Field(max_length=100)
    sync_confirmed: bool

    @field_validator('selected_calendar_ids')
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)) or any(not 0 < len(v) <= 500 or any(ord(c) < 32 for c in v) for v in value):
            raise ValueError('Choose distinct calendar IDs.')
        return value

    @field_validator('time_zone')
    @classmethod
    def valid_zone(cls, value):
        zone(value)
        return value


def provider(request):
    return CalendarProvider(request.app.state.settings, request.app.state.calendar_transport)


def status_view(db, customer, settings):
    row = db.get(CalendarConnection, customer.id)
    available = configured(settings) and not customer.demo
    connected = bool(available and row and row.status == 'connected' and row.nango_connection_id and
                     row.environment == settings.nango_environment and row.integration_id == settings.nango_calendar_integration_id)
    status = 'unavailable' if not available else row.status if row else 'disconnected'
    if status == 'connected' and not connected:
        status = 'reconnect_required'
    from .models import ServiceRequest
    from .shop_models import ShopOutreach
    issues = [{'source_kind': kind, 'source_id': item.id, 'status': item.calendar_sync_status}
              for kind, model in (('request', ServiceRequest), ('outreach', ShopOutreach))
              for item in db.scalars(select(model).where(model.customer_id == customer.id,
                 model.calendar_check.is_(True), model.calendar_sync_status.in_(('attention_needed', 'conflict', 'reconnect_required')))
                 .order_by(model.updated_at.desc(), model.id).limit(50)).all()]
    return {'configured': available, 'connected': connected, 'status': status,
            'generation': row.generation if row else 0,
            'selected_calendar_ids': row.selected_calendar_ids if row else [],
            'time_zone': row.time_zone if row else 'Etc/UTC',
            'sync_confirmed': bool(row and row.sync_confirmed),
            'attempt_id': row.attempt_id if row and row.status == 'connecting' else None,
            'sync_issues': issues}


def invalidate(db, row):
    if row.attempt_id:
        attempt = db.get(CalendarAttempt, row.attempt_id)
        if attempt:
            attempt.revoke_pending = True
            attempt.status = 'invalidated'
    row.generation += 1
    row.status = 'disconnected'
    row.nango_connection_id = None
    row.attempt_id = None
    row.selected_calendar_ids = []
    row.sync_confirmed = False


@router.get('/status')
def status(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    return status_view(db, c, request.app.state.settings)


@router.post('/connect')
def connect(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    settings = request.app.state.settings
    if not configured(settings) or c.demo:
        raise HTTPException(503, 'Google Calendar is unavailable.')
    customer_id = c.id
    lock_customer(db, customer_id)
    consume_rate(db, customer_id, 'calendar_connect', 10)
    row = db.get(CalendarConnection, customer_id)
    if not row:
        row = CalendarConnection(customer_id=customer_id, generation=0, integration_id=settings.nango_calendar_integration_id,
                                 environment=settings.nango_environment)
        db.add(row)
        db.flush()
    invalidate(db, row)
    attempt = CalendarAttempt(id=uid(), customer_id=customer_id, generation=row.generation,
                              integration_id=settings.nango_calendar_integration_id, environment=settings.nango_environment,
                              expires_at=now() + timedelta(minutes=30))
    row.attempt_id, row.status = attempt.id, 'connecting'
    row.integration_id, row.environment = settings.nango_calendar_integration_id, settings.nango_environment
    db.add(attempt)
    attempt_id, generation = attempt.id, row.generation
    db.commit()
    try:
        link, expires = provider(request).connect(customer_id, attempt_id)
    except CalendarUnavailable:
        raise HTTPException(503, 'Google Calendar connection could not be started. Try again.') from None
    lock_customer(db, customer_id)
    row, attempt = db.get(CalendarConnection, customer_id), db.get(CalendarAttempt, attempt_id)
    if row.generation != generation or row.attempt_id != attempt_id or attempt.status != 'pending':
        raise HTTPException(409, 'This connection attempt is no longer current.')
    attempt.expires_at = min(utc(attempt.expires_at), expires)
    if attempt.expires_at <= now():
        raise HTTPException(503, 'The connection session expired. Try again.')
    db.commit()
    return {'attempt_id': attempt_id, 'connect_link': link, 'expires_at': attempt.expires_at.isoformat()}


@router.post('/reconcile')
def reconcile(body: ReconcileWrite, request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    settings, customer_id = request.app.state.settings, c.id
    if not configured(settings) or c.demo:
        raise HTTPException(503, 'Google Calendar is unavailable.')
    lock_customer(db, customer_id)
    row, attempt = db.get(CalendarConnection, customer_id), db.get(CalendarAttempt, body.attempt_id)
    if not row or not attempt or attempt.customer_id != customer_id or row.attempt_id != attempt.id or utc(attempt.expires_at) <= now():
        raise HTTPException(409, 'This connection attempt expired or is not current.')
    if attempt.status == 'connected' and row.status == 'connected':
        return status_view(db, c, settings)
    if attempt.status != 'pending' or row.generation != attempt.generation or attempt.environment != settings.nango_environment or attempt.integration_id != settings.nango_calendar_integration_id:
        raise HTTPException(409, 'This connection attempt is not current.')
    consume_rate(db, customer_id, 'calendar_reconcile', 60)
    generation = row.generation
    db.commit()
    try:
        identifier = provider(request).reconcile(customer_id, body.attempt_id)
    except CalendarUnavailable:
        raise HTTPException(503, 'Google Calendar connection could not be verified. Try again.') from None
    lock_customer(db, customer_id)
    row, attempt = db.get(CalendarConnection, customer_id), db.get(CalendarAttempt, body.attempt_id)
    if not row or row.generation != generation or row.attempt_id != body.attempt_id or attempt.status != 'pending' or utc(attempt.expires_at) <= now():
        raise HTTPException(409, 'This connection attempt is no longer current.')
    if not identifier:
        raise HTTPException(409, 'A unique authorized Calendar connection was not found.')
    row.nango_connection_id, row.status = identifier, 'connected'
    attempt.nango_connection_id, attempt.status = identifier, 'connected'
    db.commit()
    return status_view(db, c, settings)


def read_binding(request, db, customer_id, *, selected=False, action='calendar_read'):
    lock_customer(db, customer_id)
    row = binding(db, customer_id, request.app.state.settings, selected=selected)
    consume_rate(db, customer_id, action, 60)
    values = (row.generation, row.nango_connection_id, list(row.selected_calendar_ids), row.time_zone)
    db.commit()
    return values


@router.get('/calendars')
def calendars(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    customer_id = c.id
    generation, identifier, selected, _ = read_binding(request, db, customer_id)
    try:
        rows = provider(request).calendars(identifier)
    except CalendarUnavailable as exc:
        provider_failure(db, customer_id, generation, identifier, exc)
    unchanged(db, customer_id, request.app.state.settings, generation, identifier)
    return {'calendars': [{'id': v['id'], 'summary': v['summary'] or 'Calendar', 'primary': bool(v['primary']),
                          'time_zone': v['timeZone'] or 'UTC', 'selected': v['id'] in selected} for v in rows]}


@router.put('/preferences')
def preferences(body: PreferencesWrite, request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    settings, customer_id = request.app.state.settings, c.id
    generation, identifier, _, _ = read_binding(request, db, customer_id)
    try:
        rows = provider(request).calendars(identifier)
    except CalendarUnavailable as exc:
        provider_failure(db, customer_id, generation, identifier, exc)
    allowed = {v['id'] for v in rows}
    if not set(body.selected_calendar_ids).issubset(allowed):
        raise HTTPException(422, 'Choose calendars available to this Google account.')
    lock_customer(db, customer_id)
    row = unchanged(db, customer_id, settings, generation, identifier)
    ids = sorted(body.selected_calendar_ids)
    if ids != sorted(row.selected_calendar_ids) or row.time_zone != body.time_zone or row.sync_confirmed != body.sync_confirmed:
        row.generation += 1
        row.selected_calendar_ids, row.time_zone, row.sync_confirmed = ids, body.time_zone, body.sync_confirmed
    db.commit()
    return status_view(db, c, settings)


@router.post('/availability')
def availability(body: AvailabilityWrite, request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    customer_id = c.id
    generation, identifier, selected, time_zone = read_binding(request, db, customer_id, selected=True, action='calendar_availability')
    if body.time_zone != time_zone:
        raise HTTPException(422, 'Use the saved Calendar time zone or change Calendar preferences first.')
    try:
        intervals = provider(request).freebusy(identifier, selected, body.time_min, body.time_max)
    except CalendarUnavailable as exc:
        provider_failure(db, customer_id, generation, identifier, exc)
    unchanged(db, customer_id, request.app.state.settings, generation, identifier)
    intervals += booked_intervals(db, customer_id, body.time_min, body.time_max)
    return {'slots': candidates(body.time_min, body.time_max, body.duration_minutes, body.time_zone,
                                body.day_start_hour, body.day_end_hour, intervals),
            'checked_at': now().isoformat(), 'generation': generation, 'time_zone': time_zone,
            'duration_minutes': body.duration_minutes}


@router.delete('/connection')
def disconnect(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    customer_id = c.id
    lock_customer(db, customer_id)
    row = db.get(CalendarConnection, customer_id)
    old_attempt = row.attempt_id if row else None
    if row:
        invalidate(db, row)
    db.commit()
    # Local invalidation is authoritative. A bounded best-effort remote revoke can be retried by the worker.
    attempt = db.get(CalendarAttempt, old_attempt) if old_attempt else None
    if attempt and attempt.nango_connection_id:
        try:
            provider(request).revoke(attempt.nango_connection_id, customer_id, attempt.id)
            attempt.revoke_pending = False
            db.commit()
        except CalendarUnavailable:
            db.rollback()
    return {'disconnected': True}


class SyncRetryWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_kind: Literal['request', 'outreach']
    source_id: str = Field(min_length=1, max_length=36)


@router.post('/sync/retry')
def retry_sync(body: SyncRetryWrite, request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    from .calendar_sync import MODELS, source_action, source_start
    from .calendar_models import CalendarProvision
    customer_id, settings = c.id, request.app.state.settings
    lock_customer(db, customer_id)
    source = db.get(MODELS[body.source_kind], body.source_id)
    if not source or source.customer_id != customer_id or not source.calendar_check:
        raise HTTPException(404, 'Appointment not found.')
    if source_action(source, body.source_kind) != 'upsert':
        raise HTTPException(422, 'Retry is available only for a confirmed appointment.')
    row = binding(db, customer_id, settings)
    if not row.sync_confirmed:
        raise HTTPException(422, 'Enable confirmed appointment copies in Calendar preferences first.')
    operation = db.scalar(select(CalendarOperation).where(CalendarOperation.customer_id == customer_id,
                          CalendarOperation.source_kind == body.source_kind, CalendarOperation.source_id == body.source_id))
    if operation and operation.claim_token and operation.lease_until and utc(operation.lease_until) > now():
        raise HTTPException(409, 'Calendar sync is already in progress.')
    adopted_provision = None
    if operation and operation.nango_connection_id != row.nango_connection_id:
        prior = db.scalar(select(CalendarProvision).where(CalendarProvision.customer_id == customer_id,
                          CalendarProvision.nango_connection_id == operation.nango_connection_id))
        if not prior:
            raise HTTPException(422, 'The previous Calendar copy cannot be verified. Review the original Google account.')
        if prior.status == 'pending' and operation.calendar_id is None and operation.applied_hash is None:
            # A persisted definite provider rejection proves there was no calendar creation.
            adopted_provision = (None, prior.nonce)
        else:
            try:
                matches = [v for v in provider(request).calendars(row.nango_connection_id)
                           if v.get('description') == 'estimoto-plus-calendar:' + prior.nonce and v.get('accessRole') == 'owner'
                           and (operation.calendar_id is None or v['id'] == operation.calendar_id)]
            except CalendarUnavailable as exc:
                provider_failure(db, customer_id, row.generation, row.nango_connection_id, exc, admission=True)
            if len(matches) != 1:
                raise HTTPException(422, 'Reconnect the Google account that owns the existing Estimoto + calendar. A second copy will not be created.')
            adopted_provision = (matches[0]['id'], prior.nonce)
    consume_rate(db, customer_id, 'calendar_sync_retry', 10)
    checked = check_slots(db, settings, request.app.state.calendar_transport, customer_id,
                          [source_start(source, body.source_kind)], source.duration_minutes, row.generation,
                          exclude=(body.source_kind, body.source_id))
    source.calendar_generation = checked['calendar_generation']
    source.calendar_selected_ids = checked['calendar_selected_ids']
    source.calendar_sync_enabled = True
    # The confirmed instant, original reservation duration and review timezone never change.
    source.calendar_sync_status, source.calendar_sync_message = 'pending', 'Calendar copy is pending.'
    if operation:
        if operation.nango_connection_id != row.nango_connection_id:
            operation.nango_connection_id, operation.calendar_id = row.nango_connection_id, adopted_provision[0]
        operation.generation, operation.attempts, operation.next_attempt_at = row.generation, 0, now()
        operation.state = 'uncertain'  # Always reconcile the existing exact event ID before writing.
        operation.claim_token, operation.lease_until = None, None
    provision = db.scalar(select(CalendarProvision).where(CalendarProvision.customer_id == customer_id,
                          CalendarProvision.nango_connection_id == row.nango_connection_id))
    if adopted_provision:
        if not provision:
            provision = CalendarProvision(customer_id=customer_id, nango_connection_id=row.nango_connection_id, nonce=adopted_provision[1])
            db.add(provision)
        provision.calendar_id, provision.status = adopted_provision[0], 'ready' if adopted_provision[0] else 'pending'
    if provision and provision.status == 'attention_needed':
        provision.status = 'uncertain'  # Retry only the nonce lookup; never issue another creation POST.
    db.commit()
    return {'source_kind': body.source_kind, 'source_id': body.source_id,
            'calendar_sync_status': source.calendar_sync_status, 'calendar_sync_message': source.calendar_sync_message}
