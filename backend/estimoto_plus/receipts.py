"""Private repair receipts with durable replay and deletion recovery.

Reservation precedes disk writes. A lost commit acknowledgement never deletes
an object that may already have been saved. Deletion tombstones outlive records
so an old retry cannot resurrect a removed attachment.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import timedelta
from threading import BoundedSemaphore
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .auth import current_customer, db_session
from .graph import lock_customer
from .graph_models import KnowledgeRecord, KnowledgeReceipt
from .models import Customer, now, uid

router = APIRouter(prefix="/v1/knowledge/records/{record_id}/receipts")
MAX_BYTES = 10 * 1024 * 1024
MAX_CUSTOMER_BYTES = 250 * 1024 * 1024
_pdf_slots = BoundedSemaphore(2)


def receipt_view(row):
    return {"id": row.id, "filename": row.filename, "content_type": row.content_type,
            "byte_size": row.byte_size, "created_at": row.created_at.isoformat()}


def record_owned(db, customer_id, record_id):
    row = db.get(KnowledgeRecord, record_id)
    if row is None or row.customer_id != customer_id:
        raise HTTPException(404, "History entry not found.")
    return row


def _path(settings, name):
    if str(UUID(name)) != name:
        raise ValueError("Invalid stored receipt identity")
    return Path(settings.photo_dir) / "receipts" / name


def _sync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def erase_receipt(row):
    row.status, row.record_id = "deleted", None
    row.cleanup_retry_at = None
    row.filename, row.content_type, row.sha256, row.byte_size = "", "", "", 0


def recover_deletions(db, customer_id, settings):
    # Called with customer writes serialized. Retained markers make a failed
    # disk delete retryable without restoring access to the removed file.
    rows = db.scalars(select(KnowledgeReceipt).where(KnowledgeReceipt.customer_id == customer_id,
        KnowledgeReceipt.status == "deleted", KnowledgeReceipt.storage_name.is_not(None),
        or_(KnowledgeReceipt.cleanup_retry_at.is_(None), KnowledgeReceipt.cleanup_retry_at <= now()))
        .order_by(KnowledgeReceipt.created_at).limit(100)).all()
    for row in rows:
        row.cleanup_retry_at = now() + timedelta(minutes=5)
        path = _path(settings, row.storage_name)
        try:
            path.unlink(missing_ok=True)
            path.with_suffix(".pending").unlink(missing_ok=True)
            if path.parent.exists():
                _sync_directory(path.parent)
        except OSError:
            continue
        row.storage_name = None
        row.cleanup_retry_at = None
    if rows:
        db.commit()


def expire_staging(db, customer_id):
    # The same customer lock guards all disk writes, so the recheck cannot
    # erase an upload that another process is currently finishing.
    for row in db.scalars(select(KnowledgeReceipt).where(KnowledgeReceipt.customer_id == customer_id,
            KnowledgeReceipt.status == "staging", KnowledgeReceipt.created_at < now() - timedelta(days=1))
            .order_by(KnowledgeReceipt.created_at).limit(100)):
        erase_receipt(row)
    db.commit()


def reconcile_receipts(session_factory, settings):
    """Bounded worker cleanup; removed receipts do not require another login."""
    from sqlalchemy import and_
    with session_factory() as db:
        ids = list(db.scalars(select(KnowledgeReceipt.customer_id).where(or_(
            and_(KnowledgeReceipt.status == "deleted", KnowledgeReceipt.storage_name.is_not(None),
                 or_(KnowledgeReceipt.cleanup_retry_at.is_(None), KnowledgeReceipt.cleanup_retry_at <= now())),
            and_(KnowledgeReceipt.status == "staging", KnowledgeReceipt.created_at < now() - timedelta(days=1)),
        )).order_by(KnowledgeReceipt.created_at).limit(100)))
        db.rollback()
        for customer_id in dict.fromkeys(ids):
            lock_customer(db, customer_id)
            expire_staging(db, customer_id)
            lock_customer(db, customer_id)
            recover_deletions(db, customer_id, settings)
            db.commit()


def validate_receipt(data, mime):
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Use a receipt of 10 MB or less.")
    if not data:
        raise HTTPException(415, "Choose a JPEG, PNG, WebP or PDF receipt.")
    if mime in {"image/jpeg", "image/png", "image/webp"}:
        from .capture_routes import validate_image
        try:
            validate_image(data, mime, max_bytes=MAX_BYTES)
        except HTTPException as exc:
            if exc.status_code == 503:
                raise
            raise HTTPException(415, "Choose a valid JPEG, PNG or WebP receipt.") from None
        return
    if mime != "application/pdf":
        raise HTTPException(415, "Choose a JPEG, PNG, WebP or PDF receipt.")
    if not _pdf_slots.acquire(blocking=False):
        raise HTTPException(503, "Receipt validation is busy. Keep this file and retry shortly.")
    try:
        result = subprocess.run([sys.executable, "-m", "estimoto_plus.receipt_pdf"], input=data,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        if result.returncode:
            raise HTTPException(415, "Use a flattened, unencrypted receipt PDF of up to 50 pages, or upload a photo.")
    except subprocess.TimeoutExpired:
        raise HTTPException(415, "This PDF could not be opened. Try a photo or a simpler PDF.") from None
    finally:
        _pdf_slots.release()


def _save(record_id, customer_id, key, data, mime, filename, request):
    settings = request.app.state.settings
    image_hash = hashlib.sha256(data).hexdigest()
    payload_hash = hashlib.sha256(json.dumps([record_id, image_hash, mime, filename]).encode()).hexdigest()
    with request.app.state.session_factory() as db:
        lock_customer(db, customer_id)
        record_owned(db, customer_id, record_id)
        recover_deletions(db, customer_id, settings)
        lock_customer(db, customer_id)
        db.expire_all()
        record_owned(db, customer_id, record_id)
        existing = db.scalar(select(KnowledgeReceipt).where(KnowledgeReceipt.customer_id == customer_id,
                                                          KnowledgeReceipt.idempotency_key == key))
        if existing:
            if existing.status == "deleted":
                raise HTTPException(410, "This receipt was deleted. Select it again to add a new copy.")
            if existing.record_id != record_id or existing.payload_hash != payload_hash:
                raise HTTPException(409, "This upload was already used for a different receipt.")
            if existing.status == "saved":
                return receipt_view(existing)
        else:
            count = db.scalar(select(func.count()).select_from(KnowledgeReceipt).where(
                KnowledgeReceipt.customer_id == customer_id, KnowledgeReceipt.record_id == record_id,
                KnowledgeReceipt.status != "deleted"))
            if count >= 10:
                raise HTTPException(422, "This entry already has 10 receipts. Remove one to add another.")
            used = db.scalar(select(func.coalesce(func.sum(KnowledgeReceipt.byte_size), 0)).where(
                KnowledgeReceipt.customer_id == customer_id, KnowledgeReceipt.status != "deleted"))
            if used + len(data) > MAX_CUSTOMER_BYTES:
                raise HTTPException(413, "Receipt storage is full. Remove a receipt before adding another.")
            from .customer_routes import consume_rate
            consume_rate(db, customer_id, "receipt_upload", 60)
            identity = uid()
            existing = KnowledgeReceipt(id=identity, customer_id=customer_id, record_id=record_id,
                idempotency_key=key, payload_hash=payload_hash, sha256=image_hash, filename=filename,
                content_type=mime, byte_size=len(data), storage_name=identity, status="staging")
            db.add(existing)
            db.commit()
            lock_customer(db, customer_id)
            db.refresh(existing)
            record_owned(db, customer_id, record_id)
            if existing.status == "deleted":
                raise HTTPException(410, "This receipt was deleted.")
            if existing.status == "saved":
                return receipt_view(existing)
        target = _path(settings, existing.storage_name)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        pending = target.with_suffix(".pending")
        # The account lock excludes concurrent writes/deletes. A terminated
        # process can leave a partial temporary file, which the same retry replaces.
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, target)
        _sync_directory(target.parent)
        existing.status = "saved"
        # Never unlink on a commit error: it may have committed remotely.
        db.commit()
        return receipt_view(existing)


@router.post("", status_code=201)
async def upload_receipt(record_id: str, request: Request, idempotency_key: str | None = Header(default=None),
                         c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    record_owned(db, c.id, record_id)
    try:
        key = str(UUID(idempotency_key or ""))
    except ValueError:
        raise HTTPException(422, "A UUID Idempotency-Key is required.") from None
    customer_id = c.id
    from .customer_routes import consume_rate
    lock_customer(db, customer_id)
    consume_rate(db, customer_id, "receipt_validation", 120)
    db.commit()
    async with request.form(max_files=1, max_fields=0, max_part_size=1024) as form:
        if set(form) != {"file"} or len(form.getlist("file")) != 1 or not isinstance(form["file"], UploadFile):
            raise HTTPException(422, "Choose one receipt file.")
        file = form["file"]
        data = await file.read(MAX_BYTES + 1)
        mime = file.content_type
        filename = (file.filename or "receipt").replace("\\", "/").rsplit("/", 1)[-1]
        filename = "".join(ch for ch in filename if ch.isprintable())[:180] or "receipt"
    await run_in_threadpool(validate_receipt, data, mime)
    return await run_in_threadpool(_save, record_id, customer_id, key, data, mime, filename, request)


@router.get("/{receipt_id}")
def read_receipt(record_id: str, receipt_id: str, request: Request,
                 c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    record_owned(db, c.id, record_id)
    row = db.get(KnowledgeReceipt, receipt_id)
    if row is None or row.customer_id != c.id or row.record_id != record_id or row.status != "saved":
        raise HTTPException(404, "Receipt not found.")
    try:
        with _path(request.app.state.settings, row.storage_name).open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) != row.byte_size or hashlib.sha256(data).hexdigest() != row.sha256:
            raise OSError("Receipt integrity")
    except (OSError, ValueError):
        raise HTTPException(503, "This receipt is temporarily unavailable. Please retry.") from None
    return Response(data, media_type=row.content_type, headers={
        "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'",
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.filename, safe=""),
    })


@router.delete("/{receipt_id}", status_code=204)
def delete_receipt(record_id: str, receipt_id: str, request: Request,
                   c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    lock_customer(db, c.id)
    record_owned(db, c.id, record_id)
    row = db.get(KnowledgeReceipt, receipt_id)
    if row is None or row.customer_id != c.id or row.record_id != record_id or row.status == "deleted":
        raise HTTPException(404, "Receipt not found.")
    erase_receipt(row)
    db.commit()
    recover_deletions(db, c.id, request.app.state.settings)
