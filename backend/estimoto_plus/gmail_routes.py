"""Verified customer-only Gmail connection and bounded car-service mail scan."""
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .auth import current_customer, db_session
from .calendar_scheduling import lock_customer, utc
from .gmail_models import GmailAttempt, GmailConnection, GmailMessage
from .gmail_provider import GmailProvider, GmailUnavailable, MAX_MESSAGES, configured
from .graph_models import KnowledgeRecord
from .models import Customer, RateBucket, now, uid

router = APIRouter(prefix='/v1/mail/gmail', tags=['customer mail'])
REVOKE_LIMIT = 6


class ReconcileWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    attempt_id: str = Field(min_length=36, max_length=36)


class MessageStatusWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['new', 'saved', 'dismissed']
    knowledge_record_id: str | None = Field(default=None, min_length=36, max_length=36)


def consume_rate(db, customer_id, action, limit):
    bucket = int(now().timestamp() // 3600)
    row = db.get(RateBucket, (customer_id, action, bucket))
    if row and row.count >= limit:
        raise HTTPException(429, 'Too many mail attempts. Please try later.')
    if row:
        row.count += 1
    else:
        db.add(RateBucket(customer_id=customer_id, action=action, hour_bucket=bucket, count=1))


def provider(request):
    return GmailProvider(request.app.state.settings, getattr(request.app.state, 'gmail_transport', None))


def message_view(m):
    return {'id': m.id, 'message_id': m.message_id, 'thread_id': m.thread_id, 'received_at': utc(m.received_at).isoformat(),
            'sender_name': m.sender_name, 'sender_address': m.sender_address, 'subject': m.subject, 'snippet': m.snippet,
            'category': m.category, 'status': m.status, 'knowledge_record_id': m.knowledge_record_id,
            'gmail_url': f'https://mail.google.com/mail/u/0/#all/{m.message_id}'}


def status_view(db, customer, settings):
    row = db.get(GmailConnection, customer.id)
    available = configured(settings) and not customer.demo
    connected = bool(available and row and row.status == 'connected' and row.nango_connection_id and
                     row.environment == settings.nango_environment and row.integration_id == settings.nango_gmail_integration_id)
    status = 'unavailable' if not available else row.status if row else 'disconnected'
    if status == 'connected' and not connected:
        status = 'reconnect_required'
    counts = {'new': 0, 'saved': 0, 'dismissed': 0}
    if row:
        for state, count in db.execute(select(GmailMessage.status, func.count()).where(
                GmailMessage.customer_id == customer.id, GmailMessage.generation == row.generation).group_by(GmailMessage.status)).all():
            counts[state] = count
    return {'configured': available, 'connected': connected, 'status': status,
            'generation': row.generation if row else 0,
            'email_address': row.email_address if connected else None,
            'last_scan_at': utc(row.last_scan_at).isoformat() if row and row.last_scan_at and connected else None,
            'attempt_id': row.attempt_id if row and row.status == 'connecting' else None,
            'scope': 'Read-only. Sender, subject, date and a short preview of car-service mail from the last 90 days.',
            'message_counts': counts}


def invalidate(db, row):
    if row.attempt_id:
        attempt = db.get(GmailAttempt, row.attempt_id)
        if attempt:
            attempt.revoke_pending = True
            attempt.status = 'invalidated'
    row.generation += 1
    row.status = 'disconnected'
    row.nango_connection_id = None
    row.attempt_id = None
    row.last_scan_at = None
    # Scanned metadata belongs to the connection that read it; none survives a disconnect.
    db.execute(delete(GmailMessage).where(GmailMessage.customer_id == row.customer_id))


def binding(db, customer, settings):
    if not configured(settings) or customer.demo:
        raise HTTPException(503, 'Gmail is unavailable.')
    row = db.get(GmailConnection, customer.id)
    if not row or row.status != 'connected' or not row.nango_connection_id:
        raise HTTPException(409, 'Connect Gmail first.')
    if row.integration_id != settings.nango_gmail_integration_id or row.environment != settings.nango_environment:
        raise HTTPException(409, 'Reconnect Gmail.')
    return row


@router.get('/status')
def status(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    return status_view(db, c, request.app.state.settings)


@router.post('/connect')
def connect(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    settings = request.app.state.settings
    if not configured(settings) or c.demo:
        raise HTTPException(503, 'Gmail is unavailable.')
    customer_id = c.id
    lock_customer(db, customer_id)
    consume_rate(db, customer_id, 'gmail_connect', 10)
    row = db.get(GmailConnection, customer_id)
    if not row:
        row = GmailConnection(customer_id=customer_id, generation=0, integration_id=settings.nango_gmail_integration_id,
                              environment=settings.nango_environment)
        db.add(row)
        db.flush()
    invalidate(db, row)
    attempt = GmailAttempt(id=uid(), customer_id=customer_id, generation=row.generation,
                           integration_id=settings.nango_gmail_integration_id, environment=settings.nango_environment,
                           expires_at=now() + timedelta(minutes=30))
    row.attempt_id, row.status = attempt.id, 'connecting'
    row.integration_id, row.environment = settings.nango_gmail_integration_id, settings.nango_environment
    db.add(attempt)
    attempt_id, generation = attempt.id, row.generation
    db.commit()
    try:
        link, expires = provider(request).connect(customer_id, attempt_id)
    except GmailUnavailable:
        raise HTTPException(503, 'Gmail connection could not be started. Try again.') from None
    lock_customer(db, customer_id)
    row, attempt = db.get(GmailConnection, customer_id), db.get(GmailAttempt, attempt_id)
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
        raise HTTPException(503, 'Gmail is unavailable.')
    lock_customer(db, customer_id)
    row, attempt = db.get(GmailConnection, customer_id), db.get(GmailAttempt, body.attempt_id)
    if not row or not attempt or attempt.customer_id != customer_id or row.attempt_id != attempt.id or utc(attempt.expires_at) <= now():
        raise HTTPException(409, 'This connection attempt expired or is not current.')
    if attempt.status == 'connected' and row.status == 'connected':
        return status_view(db, c, settings)
    if attempt.status != 'pending' or row.generation != attempt.generation or attempt.environment != settings.nango_environment or attempt.integration_id != settings.nango_gmail_integration_id:
        raise HTTPException(409, 'This connection attempt is not current.')
    consume_rate(db, customer_id, 'gmail_reconcile', 60)
    generation = row.generation
    db.commit()
    adapter = provider(request)
    try:
        identifier = adapter.reconcile(customer_id, body.attempt_id)
    except GmailUnavailable:
        raise HTTPException(503, 'Gmail connection could not be verified. Try again.') from None
    address = None
    if identifier:
        try:
            address = adapter.profile(identifier)
        except GmailUnavailable:
            address = None
    lock_customer(db, customer_id)
    row, attempt = db.get(GmailConnection, customer_id), db.get(GmailAttempt, body.attempt_id)
    if not row or row.generation != generation or row.attempt_id != body.attempt_id or attempt.status != 'pending' or utc(attempt.expires_at) <= now():
        raise HTTPException(409, 'This connection attempt is no longer current.')
    if not identifier:
        raise HTTPException(409, 'A unique authorized Gmail connection was not found.')
    row.nango_connection_id, row.status, row.email_address = identifier, 'connected', address
    attempt.nango_connection_id, attempt.status = identifier, 'connected'
    db.commit()
    return status_view(db, c, settings)


def messages_view(db, customer_id, generation):
    rows = db.scalars(select(GmailMessage).where(GmailMessage.customer_id == customer_id, GmailMessage.generation == generation)
                      .order_by(GmailMessage.received_at.desc(), GmailMessage.id).limit(100)).all()
    return {'messages': [message_view(m) for m in rows]}


@router.get('/messages')
def messages(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    row = binding(db, c, request.app.state.settings)
    return messages_view(db, c.id, row.generation)


@router.post('/scan')
def scan(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    settings, customer_id = request.app.state.settings, c.id
    lock_customer(db, customer_id)
    row = binding(db, c, settings)
    consume_rate(db, customer_id, 'gmail_scan', 6)
    generation, connection, attempt_id = row.generation, row.nango_connection_id, row.attempt_id
    known = set(db.scalars(select(GmailMessage.message_id).where(GmailMessage.customer_id == customer_id)).all())
    db.commit()
    adapter = provider(request)
    fetched = []
    try:
        adapter.verify_connection(connection, customer_id, attempt_id)
        for identifier in adapter.list_messages(connection):
            if identifier in known:
                continue
            fetched.append(adapter.message(connection, identifier))
            if len(fetched) >= MAX_MESSAGES:
                break
    except GmailUnavailable as exc:
        if exc.status in (401, 403, 404):
            lock_customer(db, customer_id)
            row = db.get(GmailConnection, customer_id)
            if row and row.generation == generation and row.status == 'connected':
                row.status = 'reconnect_required'
                db.commit()
            raise HTTPException(409, 'Gmail access needs to be renewed. Reconnect to scan again.') from None
        raise HTTPException(503, 'Gmail could not be read right now. Try again later.') from None
    lock_customer(db, customer_id)
    row = db.get(GmailConnection, customer_id)
    if not row or row.generation != generation or row.status != 'connected':
        raise HTTPException(409, 'The Gmail connection changed. Refresh and try again.')
    existing = set(db.scalars(select(GmailMessage.message_id).where(GmailMessage.customer_id == customer_id)).all())
    for item in fetched:
        if item['message_id'] in existing:
            continue
        db.add(GmailMessage(id=uid(), customer_id=customer_id, generation=generation, **item))
        existing.add(item['message_id'])
    row.last_scan_at = now()
    db.commit()
    return {'scanned': len(fetched), **messages_view(db, customer_id, generation)}


@router.put('/messages/{message_id}/status')
def message_status(message_id: str, body: MessageStatusWrite, request: Request,
                   c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    lock_customer(db, c.id)
    row = binding(db, c, request.app.state.settings)
    message = db.get(GmailMessage, message_id)
    if not message or message.customer_id != c.id or message.generation != row.generation:
        raise HTTPException(404, 'Message not found.')
    if body.knowledge_record_id:
        record = db.get(KnowledgeRecord, body.knowledge_record_id)
        if not record or record.customer_id != c.id:
            raise HTTPException(404, 'History entry not found.')
    message.status = body.status
    message.knowledge_record_id = body.knowledge_record_id if body.status == 'saved' else None
    db.commit()
    return message_view(message)


@router.delete('/connection')
def disconnect(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    customer_id = c.id
    lock_customer(db, customer_id)
    row = db.get(GmailConnection, customer_id)
    old_attempt = row.attempt_id if row else None
    if row:
        invalidate(db, row)
    db.commit()
    # Local invalidation is authoritative. A bounded best-effort remote revoke is retried by the worker.
    attempt = db.get(GmailAttempt, old_attempt) if old_attempt else None
    if attempt and attempt.nango_connection_id:
        try:
            provider(request).revoke(attempt.nango_connection_id, customer_id, attempt.id)
            attempt.revoke_pending = False
            db.commit()
        except GmailUnavailable:
            db.rollback()
    return {'disconnected': True}


def retry_gmail_revocations(settings, factory, transport=None):
    """Worker pass: finish revoking Gmail grants whose disconnect could not reach Nango."""
    if not configured(settings):
        return 0
    with factory() as db:
        ids = db.scalars(select(GmailAttempt.id).where(GmailAttempt.revoke_pending.is_(True), GmailAttempt.revoke_attempts < REVOKE_LIMIT,
                                                       GmailAttempt.next_revoke_at <= now())
                         .order_by(GmailAttempt.next_revoke_at, GmailAttempt.id).limit(20)).all()
    revoked = 0
    for identifier in ids:
        with factory() as db:
            attempt = db.get(GmailAttempt, identifier)
            customer_id = attempt.customer_id
            db.rollback()
            lock_customer(db, customer_id)
            attempt = db.get(GmailAttempt, identifier)
            if not attempt.revoke_pending or attempt.revoke_attempts >= REVOKE_LIMIT:
                continue
            if attempt.integration_id != settings.nango_gmail_integration_id or attempt.environment != settings.nango_environment:
                continue
            attempt.revoke_attempts += 1
            attempt.next_revoke_at = now() + timedelta(minutes=2 ** attempt.revoke_attempts)
            adapter = GmailProvider(settings, transport)
            try:
                connection = attempt.nango_connection_id or adapter.reconcile(customer_id, attempt.id, require_usable=False)
                if connection:
                    adapter.revoke(connection, customer_id, attempt.id)
                    attempt.revoke_pending = False
                    revoked += 1
                elif utc(attempt.expires_at) < now():
                    attempt.revoke_pending = False
                else:
                    attempt.revoke_attempts -= 1
                    attempt.next_revoke_at = utc(attempt.expires_at) + timedelta(minutes=1)
            except GmailUnavailable:
                pass
            db.commit()
    return revoked
