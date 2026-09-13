import hashlib
from io import BytesIO
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from starlette.datastructures import UploadFile
from fastapi.responses import Response, JSONResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_customer, db_session
from .models import Customer, Estimate, Outbox, Photo, Provider, Reminder, Repair, RequestEvent, ServiceRequest, Vehicle, now, uid
from .postal import canonical_zip
from .schemas import AssistantInput, EstimateCreate, ProfileWrite, ReminderCreate, RequestCreate, VehicleCreate, VehicleUpdate
from .workflow import creation_payload, payload_hash, queue_cancellation

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
    v = owned(db, Vehicle, body.vehicle_id, c)
    service_zip = canonical_zip(c.postal_code)
    if not service_zip:
        raise HTTPException(422, "Save a valid ZIP code before requesting service.")
    p = db.get(Provider, body.provider_id)
    if not p or not p.public_visible or p.demo_only != c.demo or not p.accepting_requests or body.specialty not in p.specialties or service_zip not in p.postal_codes:
        return JSONResponse(status_code=409, content={
            "detail": "Provider is not accepting this request.", "code": "request_not_created",
        })
    if not c.demo and not (request.app.state.settings.bridge_url and request.app.state.settings.bridge_key):
        raise HTTPException(503, "Requests are unavailable right now. Please try again later.")
    status = "local_preview" if c.demo else "queued"
    r = ServiceRequest(id=uid(), customer_id=c.id, vehicle_id=body.vehicle_id, provider_id=body.provider_id,
                       specialty=body.specialty, description=body.description, preferred_time=body.preferred_time,
                       idempotency_key=idempotency_key, payload_hash=digest, service_postal_code=service_zip,
                       delivery_status=status, created_at=now(), updated_at=now())
    db.add(r)
    try:
        db.flush()
        db.add(RequestEvent(request_id=r.id, status="requested", message="Request created."))
        if not c.demo:
            snapshot = creation_payload(r, c, v, p)
            db.add(Outbox(request_id=r.id, payload=snapshot, payload_hash=payload_hash(snapshot)))
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
    owned(db, ServiceRequest, request_id, c)
    stamp = now()
    changed = db.execute(update(ServiceRequest).where(
        ServiceRequest.id == request_id,
        ServiceRequest.customer_id == c.id,
        ServiceRequest.status.in_(("requested", "accepted", "scheduled")),
    ).values(status="cancelled", updated_at=stamp).returning(ServiceRequest.id)).first()
    if not changed:
        db.rollback()
        raise HTTPException(409, "This request can no longer be cancelled.")
    db.expire_all()
    r = db.get(ServiceRequest, request_id)
    creation = db.scalar(select(Outbox).where(Outbox.request_id == r.id, Outbox.kind == "create").with_for_update())
    if creation and (creation.attempts > 0 or creation.receipt_id):
        creation.suppressed = True
        queue_cancellation(db, r, creation)
    elif creation:
        creation.suppressed = True
    r.delivery_status = "cancelled"
    db.add(RequestEvent(request_id=r.id, status="cancelled", message="Cancelled by customer."))
    db.commit()
    db.refresh(r)
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
async def upload_photo(estimate_id: str, request: Request,
                       c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    e = owned(db, Estimate, estimate_id, c)
    if e.status != "draft":
        raise HTTPException(409, "Photos can only be added to drafts.")
    async with request.form(max_files=1, max_fields=1, max_part_size=1024) as form:
        file = form.get("file")
        label = form.get("label")
        if not isinstance(file, UploadFile) or not isinstance(label, str):
            raise HTTPException(422, "Photo and label are required.")
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
    try:
        db.commit()
    except Exception:
        (path / storage_name).unlink(missing_ok=True)
        raise
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
    car = owned(db, Vehicle, body.vehicle_id, c) if body.vehicle_id else None
    message = body.message.lower()
    specialty = body.specialty
    if specialty is None:
        for category, pattern in (
            ("pdr", r"\b(hail|dents?|dings?|pdr)\b"),
            ("collision", r"\b(crash|collision|accident|bumper|bodywork|paint)\b|body damage"),
            ("mechanical", r"\b(brakes?|engine|mechanic|mechanical|battery|noise)\b|won.t start|warning light"),
            ("maintenance", r"\b(oil|tires?|tyres?|pressure|filter|maintenance|service)\b"),
        ):
            if re.search(pattern, message):
                specialty = category
                break
    postal = canonical_zip(body.postal_code or c.postal_code)
    wants_provider = bool(re.search(r"\b(find|connect|someone|technician|tech|shop|book|request|repair|fix)\b|come to", message))
    mobile = body.mobile_only or bool(re.search(r"\bmobile\b|at (my )?(home|house|work)|driveway|come to", message))
    urgent = bool(re.search(r"brakes? (fail(ed|ure)?|not working)|smoke|overheat|fuel leak|burning smell|airbag|high voltage|unsafe|oil pressure", message))
    intent = "find_provider" if wants_provider and specialty and postal and car else ("clarify" if wants_provider else "advice")
    matches = [p for p in matching_providers(db, specialty, postal, mobile, c.demo) if p.accepting_requests] if intent == "find_provider" else []
    if intent == "clarify":
        missing = [name for name, value in (("repair type", specialty), ("vehicle", car), ("postal code", postal)) if not value]
        reply = "To find a provider, please share your " + " and ".join(missing or ["repair details"]) + "."
    elif intent == "find_provider":
        reply = (f"These {'mobile ' if mobile else ''}providers list your service area and specialty. Choose one to review your request; they will confirm availability and pricing."
                 if matches else "I couldn't find an opted-in provider matching those details. Try another service or a shop instead of mobile help.")
    elif re.search(r"tire|tyre|pressure", message):
        reply = "Use the cold tire pressure on the driver-door placard or in your owner's manual. Check with a gauge when the tires are cold. If a tire keeps losing pressure or has visible damage, have a technician inspect it."
    elif "oil" in message:
        reply = "Your owner's manual gives the correct oil specification and service interval for your engine. Check the date and mileage of your last service, then save a reminder in your garage."
    elif re.search(r"estimate|cost|price", message):
        reply = "An estimate separates the work, parts and labor needed for your repair. Your Estimates tab holds the shop's figures and review status. I can help you find a PDR technician or collision shop for a specific concern."
    elif "filter" in message:
        reply = "Your owner's manual identifies the correct filter and replacement interval. Cabin and engine air filters serve different purposes; check the procedure for your vehicle before replacing either. A technician can help if access requires removing other components."
    else:
        reply = "I can help you understand an estimate, plan routine maintenance, or find a technician. Try 'Find mobile dent repair' or 'How do I check tire pressure?'"
    if urgent:
        # Safety guidance precedes matching, even when the user requests a shop.
        reply = "Avoid driving if the vehicle may be unsafe. Stop somewhere safe and arrange professional help; contact emergency services when appropriate. " + (reply if wants_provider else "I can help you find a qualified repair provider.")
    videos = []
    if not urgent and not wants_provider and re.search(r"how|video|tutorial", message) and re.search(r"oil|tire|tyre|pressure|filter", message):
        topic = "check tire pressure" if re.search(r"tire|tyre|pressure", message) else ("oil service" if "oil" in message else "air filter replacement")
        vehicle_title = f"{car.year} {car.make} {car.model}" if car else "car"
        search = quote(f"{vehicle_title} {topic}", safe="")
        videos = [{"title": "Search YouTube for this maintenance topic", "url": f"https://www.youtube.com/results?search_query={search}", "source": "YouTube search · review vehicle compatibility"}]
    return {"reply": reply, "intent": intent, "specialty": specialty,
            "providers": [provider(p) for p in matches], "videos": videos}
