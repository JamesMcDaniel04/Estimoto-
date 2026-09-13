import hashlib
from io import BytesIO
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_customer, db_session
from .models import Customer, Estimate, Outbox, Photo, Provider, Reminder, Repair, RequestEvent, ServiceRequest, Vehicle, now, uid
from .schemas import AssistantInput, EstimateCreate, ProfileWrite, ReminderCreate, RequestCreate, VehicleCreate, VehicleUpdate

router = APIRouter(prefix="/v1")


def iso(value):
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else value


def profile(c):
    return {k: getattr(c, k) for k in ("id", "email", "name", "phone", "postal_code", "contact_preference")}


def vehicle(v):
    return {k: getattr(v, k) for k in ("id", "nickname", "year", "make", "model", "vin", "mileage", "insurer", "policy_number")}


def provider(p):
    return {k: getattr(p, k) for k in ("id", "name", "kind", "specialties", "postal_codes", "city", "address", "phone", "mobile_service", "accepting_requests", "description")}


def request_view(db, r):
    events = db.scalars(select(RequestEvent).where(RequestEvent.request_id == r.id).order_by(RequestEvent.created_at, RequestEvent.id)).all()
    return {"id": r.id, "vehicle_id": r.vehicle_id, "provider_id": r.provider_id, "specialty": r.specialty,
            "description": r.description, "preferred_time": r.preferred_time, "status": r.status,
            "delivery_status": r.delivery_status, "created_at": iso(r.created_at), "updated_at": iso(r.updated_at),
            "scheduled_at": iso(r.scheduled_at), "events": [{"status": e.status, "message": e.message, "created_at": iso(e.created_at)} for e in events]}


def estimate_view(db, e):
    photos = db.scalars(select(Photo).where(Photo.estimate_id == e.id)).all()
    return {"id": e.id, "vehicle_id": e.vehicle_id, "discipline": e.discipline, "description": e.description,
            "claim_number": e.claim_number, "date_of_loss": e.date_of_loss, "status": e.status,
            "amount_cents": e.amount_cents, "provider_name": e.provider_name, "updated_at": iso(e.updated_at),
            "photos": [{"id": p.id, "label": p.label} for p in photos]}


def repair_view(r):
    return {"id": r.id, "vehicle_id": r.vehicle_id, "provider_name": r.provider_name, "title": r.title,
            "status": r.status, "updated_at": iso(r.updated_at), "estimated_completion": r.estimated_completion, "stages": r.stages}


def reminder_view(r):
    return {k: getattr(r, k) for k in ("id", "vehicle_id", "title", "due_date", "due_mileage", "completed")}


def owned(db, model, identifier, customer):
    obj = db.get(model, identifier)
    if obj is None or obj.customer_id != customer.id:
        raise HTTPException(404, "Not found.")
    return obj


def matching_providers(db, specialty=None, postal_code=None, mobile_only=False, demo=False):
    candidates = db.scalars(select(Provider).where(Provider.public_visible.is_(True), Provider.demo_only.is_(demo)).order_by(Provider.name)).all()
    return [p for p in candidates if (not specialty or specialty in p.specialties)
            and (not postal_code or postal_code in p.postal_codes)
            and (not mobile_only or p.mobile_service)]


@router.get("/bootstrap")
def bootstrap(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    ids = c.id
    return {"profile": profile(c), "vehicles": [vehicle(v) for v in db.scalars(select(Vehicle).where(Vehicle.customer_id == ids)).all()],
            "providers": [provider(p) for p in matching_providers(db, demo=c.demo)],
            "estimates": [estimate_view(db, e) for e in db.scalars(select(Estimate).where(Estimate.customer_id == ids)).all()],
            "repairs": [repair_view(r) for r in db.scalars(select(Repair).where(Repair.customer_id == ids)).all()],
            "requests": [request_view(db, r) for r in db.scalars(select(ServiceRequest).where(ServiceRequest.customer_id == ids)).all()],
            "reminders": [reminder_view(r) for r in db.scalars(select(Reminder).where(Reminder.customer_id == ids)).all()],
            "capabilities": {"live_requests": bool(request.app.state.settings.bridge_url and request.app.state.settings.bridge_key and not c.demo),
                             "live_estimates": False, "carfax": False, "youtube_search": False, "demo": c.demo}}


@router.put("/profile")
def update_profile(body: ProfileWrite, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.add(c)
    db.commit()
    return profile(c)


@router.post("/vehicles", status_code=201)
def create_vehicle(body: VehicleCreate, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    v = Vehicle(customer_id=c.id, **body.model_dump())
    db.add(v)
    db.commit()
    return vehicle(v)


@router.put("/vehicles/{vehicle_id}")
def update_vehicle(vehicle_id: str, body: VehicleUpdate, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    v = owned(db, Vehicle, vehicle_id, c)
    for k, val in body.model_dump(exclude_unset=True).items():
        setattr(v, k, val)
    db.commit()
    return vehicle(v)


@router.delete("/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    v = owned(db, Vehicle, vehicle_id, c)
    if any(db.scalar(select(m.id).where(m.vehicle_id == v.id)) for m in (ServiceRequest, Estimate, Repair, Reminder)):
        raise HTTPException(409, "Vehicle is in use.")
    db.delete(v)
    db.commit()


@router.get("/providers")
def providers(specialty: str | None = None, postal_code: str | None = None, mobile_only: bool = False,
              c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    if specialty and specialty not in {"pdr", "collision", "maintenance", "mechanical"}:
        raise HTTPException(422, "Unknown specialty.")
    return [provider(p) for p in matching_providers(db, specialty, postal_code, mobile_only, c.demo)]


@router.get("/requests")
def requests(c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    return [request_view(db, r) for r in db.scalars(select(ServiceRequest).where(ServiceRequest.customer_id == c.id).order_by(ServiceRequest.created_at.desc())).all()]


@router.post("/requests", status_code=201)
def create_request(body: RequestCreate, request: Request, idempotency_key: str | None = Header(default=None),
                   c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(422, "Idempotency-Key is required.")
    payload = body.model_dump()
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    existing = db.scalar(select(ServiceRequest).where(ServiceRequest.customer_id == c.id, ServiceRequest.idempotency_key == idempotency_key))
    if existing:
        if existing.payload_hash != digest:
            raise HTTPException(409, "Idempotency key was used for another request.")
        return request_view(db, existing)
    owned(db, Vehicle, body.vehicle_id, c)
    p = db.get(Provider, body.provider_id)
    if not p or not p.public_visible or p.demo_only != c.demo or not p.accepting_requests or body.specialty not in p.specialties or (c.postal_code and c.postal_code not in p.postal_codes):
        raise HTTPException(409, "Provider is not accepting this request.")
    if not c.demo and not (request.app.state.settings.bridge_url and request.app.state.settings.bridge_key):
        raise HTTPException(503, "Requests are unavailable right now. Please try again later.")
    status = "local_preview" if c.demo else "queued"
    r = ServiceRequest(customer_id=c.id, vehicle_id=body.vehicle_id, provider_id=body.provider_id,
                       specialty=body.specialty, description=body.description, preferred_time=body.preferred_time,
                       idempotency_key=idempotency_key, payload_hash=digest, delivery_status=status)
    db.add(r)
    try:
        db.flush()
        db.add(RequestEvent(request_id=r.id, status="requested", message="Request created."))
        if not c.demo:
            db.add(Outbox(request_id=r.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ServiceRequest).where(ServiceRequest.customer_id == c.id, ServiceRequest.idempotency_key == idempotency_key))
        if existing and existing.payload_hash == digest:
            return request_view(db, existing)
        raise HTTPException(409, "Idempotency key was used for another request.")
    return request_view(db, r)


@router.post("/requests/{request_id}/cancel")
def cancel_request(request_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    r = owned(db, ServiceRequest, request_id, c)
    if r.status in {"declined", "cancelled", "completed"}:
        raise HTTPException(409, "This request can no longer be cancelled.")
    r.status = "cancelled"
    r.updated_at = now()
    if r.delivery_status in {"queued", "failed", "local_preview"}:
        r.delivery_status = "cancelled"
    elif r.delivery_status == "delivered":
        db.add(Outbox(request_id=r.id, kind="cancel"))
    db.add(RequestEvent(request_id=r.id, status="cancelled", message="Cancelled by customer."))
    db.commit()
    return request_view(db, r)


@router.post("/estimates", status_code=201)
def create_estimate(body: EstimateCreate, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned(db, Vehicle, body.vehicle_id, c)
    e = Estimate(customer_id=c.id, vehicle_id=body.vehicle_id, discipline=body.discipline,
                 description=body.description, claim_number=body.claim_number, date_of_loss=iso(body.date_of_loss))
    db.add(e)
    db.commit()
    return estimate_view(db, e)


@router.post("/estimates/{estimate_id}/submit")
def submit_estimate(estimate_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned(db, Estimate, estimate_id, c)
    raise HTTPException(503, "Estimate submission is unavailable right now.")


@router.post("/estimates/{estimate_id}/photos", status_code=201)
async def upload_photo(estimate_id: str, request: Request, file: UploadFile = File(...), label: str = Form(...),
                       c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    e = owned(db, Estimate, estimate_id, c)
    if e.status != "draft":
        raise HTTPException(409, "Photos can only be added to drafts.")
    if not label.strip() or len(label) > 100:
        raise HTTPException(422, "Photo label is required.")
    data = await file.read(10 * 1024 * 1024 + 1)
    mime = file.content_type
    valid = ((mime == "image/jpeg" and data.startswith(b"\xff\xd8\xff")) or
             (mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n")) or
             (mime == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP"))
    if not valid or len(data) > 10 * 1024 * 1024:
        raise HTTPException(422, "Upload a JPEG, PNG, or WebP image under 10 MB.")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime] or image.width * image.height > 40_000_000:
                raise ValueError("Invalid image")
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "Upload a valid JPEG, PNG, or WebP image.")
    path = Path(request.app.state.settings.photo_dir)
    path.mkdir(parents=True, exist_ok=True)
    storage_name = uid()
    (path / storage_name).write_bytes(data)
    p = Photo(estimate_id=e.id, label=label.strip(), mime_type=mime, storage_name=storage_name)
    db.add(p)
    db.commit()
    return {"id": p.id, "label": p.label}


@router.get("/estimates/{estimate_id}/photos/{photo_id}")
def get_photo(estimate_id: str, photo_id: str, request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned(db, Estimate, estimate_id, c)
    p = db.get(Photo, photo_id)
    if not p or p.estimate_id != estimate_id:
        raise HTTPException(404, "Not found.")
    path = Path(request.app.state.settings.photo_dir) / p.storage_name
    if not path.is_file():
        raise HTTPException(404, "Not found.")
    return Response(path.read_bytes(), media_type=p.mime_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/reminders", status_code=201)
def create_reminder(body: ReminderCreate, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned(db, Vehicle, body.vehicle_id, c)
    r = Reminder(customer_id=c.id, vehicle_id=body.vehicle_id, title=body.title,
                 due_date=iso(body.due_date), due_mileage=body.due_mileage)
    db.add(r)
    db.commit()
    return reminder_view(r)


@router.post("/reminders/{reminder_id}/complete")
def complete_reminder(reminder_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    r = owned(db, Reminder, reminder_id, c)
    r.completed = True
    db.commit()
    return reminder_view(r)


@router.post("/assistant")
def assistant(body: AssistantInput, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    if body.vehicle_id:
        owned(db, Vehicle, body.vehicle_id, c)
    message = body.message.lower()
    specialty = body.specialty
    if specialty is None:
        if any(word in message for word in ("hail", "dent", "ding")):
            specialty = "pdr"
        elif any(word in message for word in ("crash", "collision", "accident", "body damage")):
            specialty = "collision"
        elif any(word in message for word in ("oil", "tire", "brake", "service")):
            specialty = "maintenance"
        elif any(word in message for word in ("engine", "won't start", "mechanical")):
            specialty = "mechanical"
    postal = body.postal_code or c.postal_code
    wants_provider = any(word in message for word in ("find", "shop", "technician", "repair", "help", "book"))
    intent = "find_provider" if wants_provider and specialty and postal else ("clarify" if wants_provider else "advice")
    matches = matching_providers(db, specialty, postal, body.mobile_only, c.demo) if intent == "find_provider" else []
    if intent == "clarify":
        missing = [name for name, value in (("repair type", specialty), ("postal code", postal)) if not value]
        reply = "To find a provider, please share your " + " and ".join(missing or ["repair details"]) + "."
    elif intent == "find_provider":
        reply = "Here are providers that list this service area and specialty." if matches else "I couldn't find an opted-in provider matching those details."
    elif any(word in message for word in ("brake failure", "smoke", "fuel leak", "unsafe")):
        reply = "Avoid driving if the vehicle may be unsafe. Contact a qualified professional or emergency service as appropriate."
    else:
        reply = "I can help organize the repair details and find a provider. A professional should inspect the vehicle for a diagnosis."
    search = quote(f"{specialty or 'car repair'} advice", safe="")
    return {"reply": reply, "intent": intent, "specialty": specialty,
            "providers": [provider(p) for p in matches],
            "videos": [{"title": "YouTube search results", "url": f"https://www.youtube.com/results?search_query={search}", "source": "YouTube search"}]}
