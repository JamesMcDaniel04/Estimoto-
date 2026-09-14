"""Owner-bound capture RPC. Images and account credentials never enter URLs."""
import hashlib
import json
import re
from datetime import timedelta, timezone
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Integer, String, cast, func, or_, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .auth import current_customer, db_session
from .calendar_scheduling import lock_customer
from .capture_contract import BODY_STYLES, allowed_keys, capture_hint
from .capture_models import CaptureReceipt, CaptureVinSuggestion
from .customer_routes import consume_rate, owned, MAX_CUSTOMER_PHOTO_BYTES, MAX_PHOTOS_PER_ESTIMATE
from .models import Customer, Estimate, Photo, Vehicle, now, uid

router = APIRouter(prefix='/v1/estimates/{estimate_id}/capture')
MAX_IMAGE = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
_image_decodes = BoundedSemaphore(2)
VIN = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PhotoRef(Strict):
    photo_id: str = Field(min_length=1, max_length=36)


class VinConfirm(PhotoRef):
    photo_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_vin: str = Field(max_length=32)
    vin: str = Field(min_length=17, max_length=17)


class HelpInput(Strict):
    capture_key: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=500)


def draft(db, estimate_id, customer):
    estimate = owned(db, Estimate, estimate_id, customer)
    if estimate.status != 'draft':
        raise HTTPException(409, 'Photography is closed for this estimate.')
    return estimate


def active_photo(db, estimate_id, photo_id):
    photo = db.get(Photo, photo_id)
    if not photo or photo.estimate_id != estimate_id or photo.label != 'vin':
        raise HTTPException(404, 'VIN photo not found.')
    return photo


def quota(db, customer_id, action, limit):
    # Serialize the quota and commit it before any external provider call.
    lock_customer(db, customer_id)
    consume_rate(db, customer_id, action, limit)
    db.commit()


def validate_image(data, mime, max_bytes=MAX_IMAGE):
    formats = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}
    if mime not in formats or not data or len(data) > max_bytes:
        raise HTTPException(422, f'Use a JPEG, PNG or WebP photo under {max_bytes // (1024 * 1024)} MB.')
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != formats[mime] or image.width * image.height > MAX_PIXELS:
                raise ValueError('Invalid image')
            # Compressed byte limits do not bound decoded memory. Keep at most
            # two bounded decodes live per worker, without queueing image loads.
            if not _image_decodes.acquire(blocking=False):
                raise HTTPException(503, 'Photo validation is busy. Keep this photo and retry shortly.')
            try:
                image.load()
            finally:
                _image_decodes.release()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, 'Use a valid JPEG, PNG or WebP photo.')


async def read_photo(request, *, operation=False):
    fields = {'photo', 'capture_key', 'body_style'} | ({'operation_id'} if operation else set())
    async with request.form(max_files=1, max_fields=3, max_part_size=1024) as form:
        if set(form) != fields or any(len(form.getlist(key)) != 1 for key in fields):
            raise HTTPException(422, 'Invalid capture fields.')
        photo = form.get('photo')
        if not isinstance(photo, UploadFile):
            raise HTTPException(422, 'A photo is required.')
        data = await photo.read(MAX_IMAGE + 1)
        mime = photo.content_type
        values = {key: form[key] for key in fields - {'photo'}}
        if any(not isinstance(value, str) for value in values.values()):
            raise HTTPException(422, 'Invalid capture fields.')
    await run_in_threadpool(validate_image, data, mime)
    if values['body_style'] not in BODY_STYLES:
        raise HTTPException(422, 'Choose a supported vehicle body style.')
    if operation:
        try:
            values['operation_id'] = str(UUID(values['operation_id']))
        except ValueError:
            raise HTTPException(422, 'Invalid capture operation.')
    return data, mime, values


def provider_call(request, endpoint, data, mime, fields=None):
    settings = request.app.state.settings
    origin = urlsplit(settings.bridge_url)
    if not settings.bridge_key or origin.scheme != 'https' or not origin.netloc or origin.username or origin.password:
        raise HTTPException(503, 'Capture assistance is temporarily unavailable.')
    url = f'https://{origin.netloc}/bridge/plus/capture/{endpoint}'
    try:
        with httpx.Client(transport=getattr(request.app.state, 'capture_transport', None),
                          timeout=httpx.Timeout(18, connect=4), follow_redirects=False, trust_env=False) as client:
            with client.stream('POST', url, headers={'X-Bridge-Key': settings.bridge_key},
                               files={'photo': ('capture', data, mime)}, data=fields or {}) as response:
                if response.status_code != 200:
                    raise ValueError('Provider unavailable')
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 8192:
                        raise ValueError('Provider response too large')
                    chunks.append(chunk)
                result = json.loads(b''.join(chunks))
                if not isinstance(result, dict):
                    raise ValueError('Invalid provider response')
                return result
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(503, 'Capture assistance is temporarily unavailable.')


def framing(request, data, mime, key, body):
    try:
        value = provider_call(request, 'guidance', data, mime, {'capture_key': key, 'body_style': body})
        if type(value.get('ready')) is not bool or type(value.get('available')) is not bool:
            raise HTTPException(503, 'Capture assistance is temporarily unavailable.')
        instruction = value.get('instruction')
        if not isinstance(instruction, str) or not 1 <= len(instruction) <= 500:
            raise HTTPException(503, 'Capture assistance is temporarily unavailable.')
        return {'ready': value['ready'] and value['available'], 'available': value['available'], 'instruction': instruction}
    except HTTPException:
        return {'ready': False, 'available': False, 'instruction': capture_hint(key)}


def capture_state(estimate_id, c, db):
    e = owned(db, Estimate, estimate_id, c)
    vehicle = owned(db, Vehicle, e.vehicle_id, c)
    photos = list(db.scalars(select(Photo).where(Photo.estimate_id == e.id)))
    # Current storage names are their exact immutable operation receipts. This
    # remains bounded by active photos even after years of retakes.
    receipts = list(db.scalars(select(CaptureReceipt).where(CaptureReceipt.estimate_id == e.id,
                    CaptureReceipt.status == 'saved', CaptureReceipt.id.in_([p.storage_name for p in photos]))))
    qualities = {(r.capture_key, r.result.get('sha256')): r.result.get('quality', 'not_checked') for r in receipts}
    suggestion = None
    for p in photos:
        if p.label == 'vin':
            entry = db.get(CaptureVinSuggestion, p.id)
            if entry and entry.photo_sha256 == p.sha256:
                suggestion = {'photo_id': p.id, **entry.result}
    return {'estimate_id': e.id, 'discipline': e.discipline,
            'vehicle': {key: getattr(vehicle, key) for key in ('year', 'make', 'model', 'vin')},
            'photos': [{'id': p.id, 'label': p.label, 'sha256': p.sha256,
                        'quality': qualities.get((p.label, p.sha256), 'not_checked')} for p in photos],
            'vin_suggestion': suggestion}


@router.get('')
def state(estimate_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    return capture_state(estimate_id, c, db)


@router.post('/guidance')
async def check_frame(estimate_id: str, request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    draft(db, estimate_id, c)
    data, mime, values = await read_photo(request)
    def run():
        e = draft(db, estimate_id, c)
        if values['capture_key'] not in allowed_keys(e.discipline):
            raise HTTPException(422, 'Unknown capture step.')
        if c.demo:
            return {'ready': False, 'available': False, 'instruction': capture_hint(values['capture_key'])}
        quota(db, c.id, 'capture_guidance', 240)
        result = framing(request, data, mime, values['capture_key'], values['body_style'])
        db.expire_all()
        draft(db, estimate_id, c)
        return result
    return await run_in_threadpool(run)


def recover_storage(db, customer_id, directory):
    """Bounded cleanup under the customer lock, never delete a referenced file."""
    cutoff = now() - timedelta(days=1)
    rows = list(db.scalars(select(CaptureReceipt).where(CaptureReceipt.customer_id == customer_id,
            or_((CaptureReceipt.status == 'pending') & (CaptureReceipt.lease_until < cutoff),
                (CaptureReceipt.status == 'saved') & (cast(CaptureReceipt.replaced_storage, String) != '[]')))
            .order_by(CaptureReceipt.created_at, CaptureReceipt.id).limit(100)))
    for receipt in rows:
        names = [receipt.id] if receipt.status == 'pending' else receipt.replaced_storage
        for name in names:
            # Paths are server-created operation/file names, never client URLs.
            if not isinstance(name, str) or Path(name).name != name:
                continue
            if db.scalar(select(Photo.id).where(Photo.storage_name == name).limit(1)) is None:
                (directory / name).unlink(missing_ok=True)
        receipt.replaced_storage = []
        if receipt.status == 'pending':
            receipt.status, receipt.claim_token = 'rejected', uid()
            receipt.result = {'message': 'This capture expired. Take the photo again.'}
    db.flush()


def storage_quota(db, customer_id, estimate_id, key, operation_id, byte_size, max_bytes=None, max_photos=None):
    stored = db.scalar(select(func.coalesce(func.sum(func.coalesce(Photo.byte_size, MAX_IMAGE)), 0))
                .join(Estimate, Photo.estimate_id == Estimate.id).where(Estimate.customer_id == customer_id))
    staged = db.scalar(select(func.coalesce(func.sum(cast(CaptureReceipt.result['staged_byte_size'].as_string(), Integer)), 0))
                .where(CaptureReceipt.customer_id == customer_id, CaptureReceipt.status == 'pending',
                       CaptureReceipt.id != operation_id))
    replaced = db.scalar(select(func.coalesce(func.sum(func.coalesce(Photo.byte_size, MAX_IMAGE)), 0))
                .where(Photo.estimate_id == estimate_id, Photo.label == key))
    if stored + staged - replaced + byte_size > (MAX_CUSTOMER_PHOTO_BYTES if max_bytes is None else max_bytes):
        raise HTTPException(413, 'Photo storage limit reached. Contact support.')
    count = db.scalar(select(func.count(Photo.id)).where(Photo.estimate_id == estimate_id, Photo.label != key))
    if count + 1 > (MAX_PHOTOS_PER_ESTIMATE if max_photos is None else max_photos):
        raise HTTPException(413, 'Estimate photo limit reached.')


def save_photo(estimate_id, request, c, db, data, mime, values, *, verify_framing=True, validate_capture_key=True,
               max_bytes=None, max_photos=None, max_uploads=100):
    e = owned(db, Estimate, estimate_id, c)
    key, operation_id = values['capture_key'], values['operation_id']
    if validate_capture_key and key not in allowed_keys(e.discipline):
        raise HTTPException(422, 'Unknown capture step.')
    image_hash = hashlib.sha256(data).hexdigest()
    digest = hashlib.sha256(json.dumps([image_hash, mime, key, values['body_style']]).encode()).hexdigest()
    lock_customer(db, c.id)
    directory = Path(request.app.state.settings.photo_dir)
    recover_storage(db, c.id, directory)
    receipt = db.get(CaptureReceipt, operation_id)
    if receipt:
        if receipt.customer_id != c.id or receipt.estimate_id != e.id:
            raise HTTPException(404, 'Capture operation not found.')
        if receipt.payload_hash != digest:
            raise HTTPException(409, 'This capture operation already identifies another photo.')
        if receipt.status == 'saved':
            result = receipt.result
            db.commit()
            return result
        if receipt.status == 'rejected':
            raise HTTPException(422, receipt.result['message'])
        lease = receipt.lease_until.replace(tzinfo=timezone.utc) if receipt.lease_until.tzinfo is None else receipt.lease_until
        if lease > now():
            raise HTTPException(409, 'This photo is still saving. Retry the same photo shortly.')
    draft(db, estimate_id, c)
    storage_quota(db, c.id, e.id, key, operation_id, len(data), max_bytes, max_photos)
    claim = uid()
    if not receipt:
        receipt = CaptureReceipt(id=operation_id, customer_id=c.id, estimate_id=e.id, capture_key=key, payload_hash=digest,
                                 claim_token=claim, lease_until=now() + timedelta(seconds=60),
                                 result={'staged_byte_size': len(data)})
        db.add(receipt)
    receipt.claim_token, receipt.lease_until = claim, now() + timedelta(seconds=60)
    consume_rate(db, c.id, 'photo_upload', max_uploads)
    db.commit()
    guidance = ({'ready': False, 'available': False, 'instruction': capture_hint(key)} if c.demo or not verify_framing else
                framing(request, data, mime, key, values['body_style']))
    lock_customer(db, c.id)
    db.expire_all()
    receipt = db.get(CaptureReceipt, operation_id)
    if receipt.claim_token != claim:
        raise HTTPException(409, 'This photo is being recovered. Retry the same photo shortly.')
    e = draft(db, estimate_id, c)
    if guidance['available'] and not guidance['ready']:
        receipt.status, receipt.result = 'rejected', {'message': 'Retake this photo. ' + guidance['instruction']}
        db.commit()
        raise HTTPException(422, receipt.result['message'])
    existing = list(db.scalars(select(Photo).where(Photo.estimate_id == e.id, Photo.label == key)))
    storage_quota(db, c.id, e.id, key, operation_id, len(data), max_bytes, max_photos)
    directory.mkdir(parents=True, exist_ok=True)
    # A retry after an uncertain database COMMIT reuses its one staged object.
    # Never remove bytes that a successful but unacknowledged commit may own.
    filename = operation_id
    output = directory / filename
    old_paths = [directory / p.storage_name for p in existing]
    created = False
    commit_attempted = False
    try:
        if output.exists():
            if output.stat().st_size != len(data) or hashlib.sha256(output.read_bytes()).hexdigest() != image_hash:
                raise HTTPException(409, 'The staged photo needs recovery. Keep the same capture and contact support.')
        else:
            with output.open('xb') as stream:
                created = True
                stream.write(data)
                stream.flush()
                import os
                os.fsync(stream.fileno())
            directory_fd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        photo = existing[0] if existing else Photo(id=uid(), estimate_id=e.id, label=key)
        for duplicate in existing[1:]:
            db.delete(duplicate)
        photo.storage_name, photo.mime_type, photo.sha256, photo.byte_size = filename, mime, image_hash, len(data)
        db.add(photo)
        receipt.status = 'saved'
        receipt.replaced_storage = [p.name for p in old_paths]
        receipt.result = {'id': photo.id, 'label': key, 'sha256': image_hash,
                          'quality': 'framing_checked' if guidance['ready'] else 'not_checked',
                          'warning': None if guidance['ready'] else 'Photo saved without automated framing verification.'}
        e.updated_at = now()
        commit_attempted = True
        db.commit()
    except Exception:
        db.rollback()
        if created and not commit_attempted:
            output.unlink(missing_ok=True)
        raise
    for old in old_paths:
        old.unlink(missing_ok=True)
    return receipt.result


@router.post('/photos', status_code=201)
async def upload(estimate_id: str, request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned(db, Estimate, estimate_id, c)
    data, mime, values = await read_photo(request, operation=True)
    return await run_in_threadpool(save_photo, estimate_id, request, c, db, data, mime, values)


@router.post('/vin/recognize')
def recognize_vin(estimate_id: str, body: PhotoRef, request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    draft(db, estimate_id, c)
    photo = active_photo(db, estimate_id, body.photo_id)
    old = db.get(CaptureVinSuggestion, photo.id)
    if old and old.photo_sha256 == photo.sha256:
        return {'photo_id': photo.id, **old.result}
    if c.demo:
        raise HTTPException(503, 'VIN recognition is unavailable in sample mode.')
    file = Path(request.app.state.settings.photo_dir) / photo.storage_name
    if not file.is_file() or file.stat().st_size > MAX_IMAGE:
        raise HTTPException(404, 'VIN photo not found.')
    data, mime, sha = file.read_bytes(), photo.mime_type, photo.sha256
    if hashlib.sha256(data).hexdigest() != sha:
        raise HTTPException(409, 'The VIN photo changed. Take another photo.')
    quota(db, c.id, 'capture_vin', 20)
    response = provider_call(request, 'vin-photo', data, mime)
    suggestion = response.get('suggested_vin')
    confidence = response.get('confidence')
    if (suggestion is not None and (not isinstance(suggestion, str) or not VIN.fullmatch(suggestion))) or (confidence is not None and (type(confidence) not in (int, float) or not 0 <= confidence <= 1)):
        raise HTTPException(503, 'VIN recognition is temporarily unavailable.')
    result = {'suggested_vin': suggestion, 'confidence': confidence, 'requires_confirmation': True}
    lock_customer(db, c.id)
    db.expire_all()
    draft(db, estimate_id, c)
    photo = active_photo(db, estimate_id, body.photo_id)
    if photo.sha256 != sha:
        raise HTTPException(409, 'The VIN photo changed. Try the new photo.')
    old = db.get(CaptureVinSuggestion, photo.id)
    if not old:
        old = CaptureVinSuggestion(photo_id=photo.id, customer_id=c.id, estimate_id=estimate_id)
        db.add(old)
    old.photo_sha256, old.result, old.created_at = sha, result, now()
    db.commit()
    return {'photo_id': photo.id, **result}


@router.post('/vin/confirm')
def confirm_vin(estimate_id: str, body: VinConfirm, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    value = body.vin.strip().upper()
    if not VIN.fullmatch(value):
        raise HTTPException(422, 'Enter the 17 VIN characters shown on the label.')
    lock_customer(db, c.id)
    db.expire_all()
    e = draft(db, estimate_id, c)
    photo = active_photo(db, estimate_id, body.photo_id)
    if photo.sha256 != body.photo_sha256:
        raise HTTPException(409, 'The VIN photo changed. Review the new photo before confirming.')
    changed = db.execute(update(Vehicle).where(Vehicle.id == e.vehicle_id, Vehicle.customer_id == c.id,
                        Vehicle.vin == body.expected_vin).values(vin=value).returning(Vehicle.id)).first()
    if not changed:
        current = owned(db, Vehicle, e.vehicle_id, c)
        if current.vin != value:
            raise HTTPException(409, 'Your saved VIN changed. Review it before confirming.')
    db.commit()
    return {'vin': value, 'confirmed': True}


@router.post('/help')
def help_capture(estimate_id: str, body: HelpInput, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    e = owned(db, Estimate, estimate_id, c)
    if body.capture_key not in allowed_keys(e.discipline):
        raise HTTPException(422, 'Unknown capture step.')
    quota(db, c.id, 'capture_help', 60)
    question = body.question.lower()
    if any(word in question for word in ('glare', 'dark', 'light', 'blurry', 'blur')):
        reply = 'Use even daylight, clean the camera lens, and tap the label or panel to focus. Move slightly to avoid glare, then hold still. ' + capture_hint(body.capture_key)
    elif any(word in question for word in ('camera', 'permission', 'black screen')):
        reply = 'Allow camera access for Estimoto + in your phone settings, then reopen the guide. If camera access is unavailable, choose an existing photo. Photography does not send your estimate to a shop.'
    elif any(word in question for word in ('submit', 'send', 'book', 'price')):
        reply = 'Finishing the photo guide saves your pictures. You will review the shop and shared details before submitting. The shop reviews the evidence and confirms the estimate.'
    elif any(word in question for word in ('vin', 'label', 'hinge', 'jamb')):
        reply = capture_hint('vin') + ' Any recognized VIN is a suggestion; review and confirm it before changing your saved vehicle.'
    else:
        reply = capture_hint(body.capture_key)
    return {'reply': reply}
