"""Database-claimed, at-least-once delivery of immutable bridge events."""
import json
from datetime import timedelta
from uuid import uuid4

import httpx
from sqlalchemy import or_, select, update

from .models import Outbox, Provider, ServiceRequest, now
from .postal import canonical_zip
from .workflow import payload_hash, queue_cancellation

LEASE_SECONDS = 60
MAX_RECEIPT_BYTES = 4096


def _request_lock(db, request_id):
    # A no-op write takes the request row lock on PostgreSQL and the writer
    # reservation on SQLite. Customer cancellation uses the same row first.
    return db.execute(update(ServiceRequest).where(ServiceRequest.id == request_id)
                      .values(updated_at=ServiceRequest.updated_at)
                      .returning(ServiceRequest.id)).first()


def due_ids(session_factory):
    with session_factory() as db:
        current = now()
        ids = db.scalars(select(Outbox.id).where(
            Outbox.receipt_id.is_(None), Outbox.suppressed.is_(False),
            Outbox.next_attempt_at <= current,
            or_(Outbox.claim_token.is_(None), Outbox.lease_until <= current),
        ).order_by(Outbox.next_attempt_at, Outbox.id).limit(20)).all()
        return ids


def claim(session_factory, outbox_id):
    with session_factory() as db:
        request_id = db.scalar(select(Outbox.request_id).where(Outbox.id == outbox_id))
        db.rollback()
        if not request_id or not _request_lock(db, request_id):
            db.rollback()
            return None
        item = db.get(Outbox, outbox_id)
        request = db.get(ServiceRequest, request_id)
        if not item or not request:
            db.rollback()
            return None
        current = now()
        if item.receipt_id or item.suppressed:
            db.rollback()
            return None
        payload = item.payload
        valid_payload = (isinstance(payload, dict) and item.payload_hash == payload_hash(payload)
                         and payload.get("request_id") == request_id
                         and payload.get("event") == ("created" if item.kind == "create" else "cancelled"))
        if item.kind == "create":
            provider = db.scalar(select(Provider).where(Provider.id == request.provider_id).with_for_update())
            eligible = (provider is not None and provider.public_visible and provider.accepting_requests
                        and not provider.demo_only and request.specialty in provider.specialties
                        and canonical_zip(request.service_postal_code) is not None
                        and request.service_postal_code in provider.postal_codes
                        and isinstance(payload, dict)
                        and payload.get("service_postal_code") == request.service_postal_code
                        and payload.get("provider_source_id") == provider.source_id)
            if request.status == "cancelled" or not valid_payload or not eligible:
                item.suppressed = True
                if request.status != "cancelled":
                    request.delivery_status = "failed"
                    request.updated_at = current
                db.commit()
                return "rejected"
        elif item.kind != "cancel" or not valid_payload:
            item.suppressed = True
            db.commit()
            return "rejected"
        token = str(uuid4())
        changed = db.execute(update(Outbox).where(
            Outbox.id == outbox_id, Outbox.receipt_id.is_(None), Outbox.suppressed.is_(False),
            Outbox.next_attempt_at <= current,
            or_(Outbox.claim_token.is_(None), Outbox.lease_until <= current),
        ).values(claim_token=token, lease_until=current + timedelta(seconds=LEASE_SECONDS),
                 attempts=Outbox.attempts + 1).returning(Outbox.id).execution_options(synchronize_session=False)).first()
        if not changed:
            db.rollback()
            return None
        db.commit()
        return (token, request_id, item.kind, payload)


def send(settings, transport, request_id, kind, payload):
    key = request_id if kind == "create" else f"cancel:{request_id}"
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            with client.stream("POST", settings.bridge_url, json=payload,
                               headers={"X-Bridge-Key": settings.bridge_key, "Idempotency-Key": key}) as response:
                if response.status_code not in {200, 201, 202}:
                    return None
                chunks = bytearray()
                for chunk in response.iter_bytes(chunk_size=1024):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_RECEIPT_BYTES:
                        return None
        decoded = json.loads(chunks)
    except (httpx.HTTPError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    receipt = decoded.get("receipt_id")
    return receipt if isinstance(receipt, str) and 0 < len(receipt) <= 200 and receipt.strip() else None


def finalize(session_factory, outbox_id, token, request_id, kind, receipt):
    with session_factory() as db:
        if not _request_lock(db, request_id):
            db.rollback()
            return None
        item = db.get(Outbox, outbox_id)
        request = db.get(ServiceRequest, request_id)
        if not item or not request or item.claim_token != token or item.receipt_id:
            db.rollback()
            return None
        current = now()
        values = {"claim_token": None, "lease_until": None}
        if receipt:
            values["receipt_id"] = receipt
        else:
            values["next_attempt_at"] = current + timedelta(seconds=min(3600, 2 ** min(item.attempts, 10)))
        changed = db.execute(update(Outbox).where(
            Outbox.id == outbox_id, Outbox.claim_token == token, Outbox.receipt_id.is_(None),
        ).values(**values).returning(Outbox.id).execution_options(synchronize_session=False)).first()
        if not changed:
            db.rollback()
            return None
        if kind == "create":
            if request.status == "cancelled":
                queue_cancellation(db, request, item)
            else:
                request.delivery_status = "delivered" if receipt else "failed"
                request.updated_at = current
        db.commit()
        return bool(receipt)


def deliver_batch(settings, transport, session_factory):
    delivered = failed = 0
    for outbox_id in due_ids(session_factory):
        claimed = claim(session_factory, outbox_id)
        if claimed is None:
            continue
        if claimed == "rejected":
            failed += 1
            continue
        token, request_id, kind, payload = claimed
        receipt = send(settings, transport, request_id, kind, payload)
        outcome = finalize(session_factory, outbox_id, token, request_id, kind, receipt)
        if outcome is True:
            delivered += 1
        elif outcome is False:
            failed += 1
    return {"delivered": delivered, "failed": failed}
