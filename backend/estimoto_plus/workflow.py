"""Immutable reviewed request payloads and cancellation tombstones."""
import hashlib
import json
import re

from sqlalchemy import select

from .models import Outbox, Provider


def bridge_details(customer, vehicle, *, estimate=False):
    """Validate the exact receiver bounds before an immutable send is queued."""
    contact = {"email": customer.email.strip(), "name": customer.name.strip(),
               "phone": customer.phone.strip(), "contact_preference": customer.contact_preference}
    car = {"year": vehicle.year, "make": vehicle.make.strip(), "model": vehicle.model.strip(),
           "vin": vehicle.vin.strip().upper(), "mileage": vehicle.mileage}
    if (not 1 <= len(contact["name"]) <= 200 or not 3 <= len(contact["email"]) <= 200 or
            "@" not in contact["email"][1:-1] or len(contact["phone"]) > 40 or
            (estimate and len("".join(ch for ch in contact["phone"] if ch.isdigit())) < 7)):
        raise ValueError("Save your name and a reachable phone number before submitting." if estimate else
                         "Review your saved name, email, and phone number before requesting service.")
    if (not 1950 <= car["year"] <= 2050 or not 1 <= len(car["make"]) <= 60 or
            not 1 <= len(car["model"]) <= 60 or not 0 <= car["mileage"] <= 9_999_999 or
            len(car["vin"]) > 32 or (estimate and car["vin"] and not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", car["vin"]))):
        raise ValueError("Review the vehicle year, make, model, mileage, and VIN before submitting.")
    return contact, car


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def creation_payload(request, customer, vehicle, provider) -> dict:
    contact, car = bridge_details(customer, vehicle)
    return {
        "event": "created", "request_id": request.id, "customer_id": customer.id,
        "vehicle_id": vehicle.id, "provider_source_id": provider.source_id,
        "service_postal_code": request.service_postal_code,
        "specialty": request.specialty, "description": request.description,
        "preferred_time": request.preferred_time,
        "contact": contact,
        "vehicle": car,
        "created_at": request.created_at.isoformat(),
        **({'service_mode': request.service_mode} if request.service_mode is not None else {}),
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
