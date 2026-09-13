from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .auth import bridge_authorized, db_session
from .customer_routes import estimate_view, provider, repair_view, request_view
from .delivery import deliver_batch
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


def _same_event(previous, request_id, body, scheduled_at_text):
    return (previous is not None and previous.request_id == request_id and
            previous.status == body.status and previous.message == body.message and
            previous.scheduled_at == scheduled_at_text)


@router.post("/requests/{request_id}/events")
def inbound_event(request_id: str, body: RequestInboundEvent, db: Session = Depends(db_session)):
    r = db.get(ServiceRequest, request_id)
    if not r or r.provider_id != body.provider_id:
        raise HTTPException(404, "Request not found.")
    scheduled_at_text = body.scheduled_at.astimezone(timezone.utc).isoformat() if body.scheduled_at else None
    previous = db.scalar(select(RequestEvent).where(RequestEvent.event_id == body.event_id))
    if previous:
        if _same_event(previous, request_id, body, scheduled_at_text):
            return request_view(db, r)
        raise HTTPException(409, "Event ID was already used.")
    if r.delivery_status != "delivered":
        raise HTTPException(404, "Request not found.")
    if body.status == "scheduled" and body.scheduled_at is None:
        raise HTTPException(422, "Scheduled time is required.")
    if body.status != "scheduled" and body.scheduled_at is not None:
        raise HTTPException(422, "Scheduled time is only valid for scheduling.")
    predecessors = tuple(status for status, targets in TRANSITIONS.items() if body.status in targets)
    stamp = now()
    db.rollback()  # End preliminary read transaction; the conditional write is authoritative.
    changed = db.execute(update(ServiceRequest).where(
        ServiceRequest.id == request_id,
        ServiceRequest.provider_id == body.provider_id,
        ServiceRequest.delivery_status == "delivered",
        ServiceRequest.status.in_(predecessors),
    ).values(status=body.status, updated_at=stamp,
             **({"scheduled_at": body.scheduled_at} if body.status == "scheduled" else {}))
        .returning(ServiceRequest.id)).first()
    if not changed:
        db.rollback()
        previous = db.scalar(select(RequestEvent).where(RequestEvent.event_id == body.event_id))
        if _same_event(previous, request_id, body, scheduled_at_text):
            db.expire_all()
            return request_view(db, db.get(ServiceRequest, request_id))
        raise HTTPException(409, "Invalid status transition.")
    db.add(RequestEvent(request_id=request_id, event_id=body.event_id, status=body.status,
                        message=body.message, scheduled_at=scheduled_at_text))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.scalar(select(RequestEvent).where(RequestEvent.event_id == body.event_id))
        if _same_event(previous, request_id, body, scheduled_at_text):
            db.expire_all()
            return request_view(db, db.get(ServiceRequest, request_id))
        raise HTTPException(409, "Event ID was already used.")
    db.expire_all()
    return request_view(db, db.get(ServiceRequest, request_id))


@router.post("/outbox/deliver")
def deliver_outbox(request: Request):
    settings = request.app.state.settings
    if not settings.bridge_url or not settings.bridge_key:
        raise HTTPException(503, "Bridge is unavailable.")
    return deliver_batch(settings, request.app.state.bridge_transport, request.app.state.session_factory)


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
    for k, val in body.model_dump(mode="json", exclude={"customer_id", "vehicle_id", "source_id"}).items():
        setattr(r, k, val)
    r.updated_at = now()
    db.commit()
    return repair_view(r)
