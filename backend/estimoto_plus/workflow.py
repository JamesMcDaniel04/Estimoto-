"""Immutable reviewed request payloads and cancellation tombstones."""
import hashlib
import json

from sqlalchemy import select

from .models import Outbox, Provider


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def creation_payload(request, customer, vehicle, provider) -> dict:
    return {
        "event": "created", "request_id": request.id, "customer_id": customer.id,
        "vehicle_id": vehicle.id, "provider_source_id": provider.source_id,
        "service_postal_code": request.service_postal_code,
        "specialty": request.specialty, "description": request.description,
        "preferred_time": request.preferred_time,
        "contact": {"email": customer.email, "name": customer.name, "phone": customer.phone,
                    "contact_preference": customer.contact_preference},
        "vehicle": {"year": vehicle.year, "make": vehicle.make, "model": vehicle.model,
                    "vin": vehicle.vin, "mileage": vehicle.mileage},
        "created_at": request.created_at.isoformat(),
    }


def queue_cancellation(db, request, creation: Outbox | None) -> None:
    existing = db.scalar(select(Outbox).where(Outbox.request_id == request.id, Outbox.kind == "cancel"))
    if existing:
        return
    provider_source_id = None
    if creation and isinstance(creation.payload, dict):
        provider_source_id = creation.payload.get("provider_source_id")
    if not provider_source_id:
        provider = db.get(Provider, request.provider_id)
        provider_source_id = provider.source_id if provider else None
    payload = {"event": "cancelled", "request_id": request.id,
               "provider_source_id": provider_source_id}
    db.add(Outbox(request_id=request.id, kind="cancel", payload=payload,
                  payload_hash=payload_hash(payload)))
