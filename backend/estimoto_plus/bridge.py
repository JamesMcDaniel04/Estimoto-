from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import bridge_authorized, db_session
from .customer_routes import estimate_view, provider, repair_view, request_view
from .models import Customer, Estimate, Outbox, Provider, Repair, RequestEvent, ServiceRequest, Vehicle, now
from .schemas import EstimateSnapshot, ProviderPublish, RepairSnapshot, RequestInboundEvent

router = APIRouter(prefix="/v1/bridge", dependencies=[Depends(bridge_authorized)])


@router.post("/providers")
def upsert_provider(body: ProviderPublish, db: Session = Depends(db_session)):
    p = db.scalar(select(Provider).where(Provider.source_id == body.source_id))
    if p is None:
        p = Provider(source_id=body.source_id)
        db.add(p)
    for k, value in body.model_dump().items():
        setattr(p, k, value)
    db.commit()
    return provider(p)


TRANSITIONS = {
    "requested": {"accepted", "declined", "cancelled"},
    "accepted": {"scheduled", "declined", "cancelled"},
    "scheduled": {"completed", "cancelled"},
    "declined": set(), "cancelled": set(), "completed": set(),
}


@router.post("/requests/{request_id}/events")
def inbound_event(request_id: str, body: RequestInboundEvent, db: Session = Depends(db_session)):
    r = db.get(ServiceRequest, request_id)
    if not r or r.provider_id != body.provider_id or r.delivery_status != "delivered":
        raise HTTPException(404, "Request not found.")
    scheduled_at_text = body.scheduled_at.astimezone(timezone.utc).isoformat() if body.scheduled_at else None
    previous = db.scalar(select(RequestEvent).where(RequestEvent.event_id == body.event_id))
    if previous:
        if previous.request_id == r.id and previous.status == body.status and previous.message == body.message and previous.scheduled_at == scheduled_at_text:
            return request_view(db, r)
        raise HTTPException(409, "Event ID was already used.")
    if body.status not in TRANSITIONS.get(r.status, set()):
        raise HTTPException(409, "Invalid status transition.")
    if body.status == "scheduled" and body.scheduled_at is None:
        raise HTTPException(422, "Scheduled time is required.")
    if body.status != "scheduled" and body.scheduled_at is not None:
        raise HTTPException(422, "Scheduled time is only valid for scheduling.")
    r.status = body.status
    r.updated_at = now()
    if body.status == "scheduled":
        r.scheduled_at = body.scheduled_at
    db.add(RequestEvent(request_id=r.id, event_id=body.event_id, status=body.status, message=body.message, scheduled_at=scheduled_at_text))
    db.commit()
    return request_view(db, r)


@router.post("/outbox/deliver")
def deliver_outbox(request: Request, db: Session = Depends(db_session)):
    settings = request.app.state.settings
    if not settings.bridge_url or not settings.bridge_key:
        raise HTTPException(503, "Bridge is unavailable.")
    due = db.scalars(select(Outbox).where(Outbox.receipt_id.is_(None), Outbox.next_attempt_at <= now()).order_by(Outbox.next_attempt_at).limit(20)).all()
    delivered = failed = 0
    for item in due:
        r = db.get(ServiceRequest, item.request_id)
        if not r or (item.kind == "create" and r.delivery_status == "cancelled"):
            db.delete(item)
            db.commit()
            continue
        c = db.get(Customer, r.customer_id)
        v = db.get(Vehicle, r.vehicle_id)
        p = db.get(Provider, r.provider_id)
        if item.kind == "create" and (not p or not p.public_visible or not p.accepting_requests or r.specialty not in p.specialties or (c.postal_code and c.postal_code not in p.postal_codes)):
            r.delivery_status = "failed"
            r.updated_at = now()
            db.delete(item)
            db.commit()
            failed += 1
            continue
        body = {"event": "created", "request_id": r.id, "customer_id": c.id, "vehicle_id": v.id,
                "provider_source_id": p.source_id, "specialty": r.specialty,
                "description": r.description, "preferred_time": r.preferred_time,
                "contact": {"email": c.email, "name": c.name, "phone": c.phone, "contact_preference": c.contact_preference},
                "vehicle": {"year": v.year, "make": v.make, "model": v.model, "vin": v.vin, "mileage": v.mileage},
                "created_at": r.created_at.isoformat()}
        if item.kind == "cancel":
            body = {"event": "cancelled", "request_id": r.id, "provider_source_id": p.source_id}
        try:
            with httpx.Client(timeout=10, transport=request.app.state.bridge_transport) as client:
                response = client.post(settings.bridge_url, json=body, headers={"X-Bridge-Key": settings.bridge_key, "Idempotency-Key": (r.id if item.kind == "create" else f"cancel:{r.id}")})
            receipt = response.json().get("receipt_id") if response.status_code in {200, 201, 202} else None
        except (httpx.HTTPError, ValueError):
            receipt = None
        if isinstance(receipt, str) and receipt:
            item.receipt_id = receipt
            if item.kind == "create":
                r.delivery_status = "delivered"
            delivered += 1
        else:
            item.attempts += 1
            item.next_attempt_at = now() + timedelta(seconds=min(3600, 2 ** min(item.attempts, 10)))
            if item.kind == "create":
                r.delivery_status = "failed"
            failed += 1
        r.updated_at = now()
        db.commit()
    return {"delivered": delivered, "failed": failed}


def existing_binding(db, customer_id, vehicle_id):
    customer = db.get(Customer, customer_id)
    vehicle = db.get(Vehicle, vehicle_id)
    if not customer or not vehicle or vehicle.customer_id != customer_id or customer.demo:
        raise HTTPException(404, "Customer or vehicle relationship not found.")


@router.post("/estimates/snapshots")
def estimate_snapshot(body: EstimateSnapshot, db: Session = Depends(db_session)):
    existing_binding(db, body.customer_id, body.vehicle_id)
    e = db.scalar(select(Estimate).where(Estimate.source_id == body.source_id))
    if e and (e.customer_id != body.customer_id or e.vehicle_id != body.vehicle_id):
        raise HTTPException(409, "Snapshot binding cannot change.")
    if not e:
        e = Estimate(source_id=body.source_id, customer_id=body.customer_id, vehicle_id=body.vehicle_id)
        db.add(e)
    for k, val in body.model_dump(exclude={"customer_id", "vehicle_id", "source_id"}).items():
        setattr(e, k, val.isoformat() if hasattr(val, "isoformat") else val)
    e.updated_at = now()
    db.commit()
    return estimate_view(db, e)


@router.post("/repairs/snapshots")
def repair_snapshot(body: RepairSnapshot, db: Session = Depends(db_session)):
    existing_binding(db, body.customer_id, body.vehicle_id)
    r = db.scalar(select(Repair).where(Repair.source_id == body.source_id))
    if r and (r.customer_id != body.customer_id or r.vehicle_id != body.vehicle_id):
        raise HTTPException(409, "Snapshot binding cannot change.")
    if not r:
        r = Repair(source_id=body.source_id, customer_id=body.customer_id, vehicle_id=body.vehicle_id)
        db.add(r)
    for k, val in body.model_dump(exclude={"customer_id", "vehicle_id", "source_id"}).items():
        if k == "stages":
            val = [{"title": s.title, "status": s.status, "date": s.date.isoformat() if s.date else None} for s in val]
        elif hasattr(val, "isoformat"):
            val = val.isoformat()
        setattr(r, k, val)
    r.updated_at = now()
    db.commit()
    return repair_view(r)
