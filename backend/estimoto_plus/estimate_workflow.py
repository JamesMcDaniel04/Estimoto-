"""Authoritative estimate snapshots bind to a customer-owned submitted draft."""
from sqlalchemy import select

from .models import Estimate

STATUS_RANK = {"submitted": 1, "reviewing": 2, "ready": 3, "approved": 4}


def apply_submitted_snapshot(db, estimate: Estimate, body, frozen_payload: dict) -> None:
    if (body.estimate_id != estimate.id or body.customer_id != estimate.customer_id or
            body.vehicle_id != estimate.vehicle_id or body.provider_source_id != frozen_payload.get("provider_source_id") or
            body.discipline != estimate.discipline or body.description != estimate.description or
            body.claim_number != estimate.claim_number or str(body.date_of_loss or "") != str(estimate.date_of_loss or "")):
        raise ValueError("Estimate snapshot binding does not match the submission")
    if estimate.source_id and estimate.source_id != body.source_id:
        raise ValueError("Estimate source binding cannot change")
    if STATUS_RANK[body.status] < STATUS_RANK.get(estimate.status, 0):
        raise ValueError("Estimate status cannot regress")
    if body.status in {"ready", "approved"} and body.amount_cents is None:
        raise ValueError("Ready estimate needs an authoritative amount")
    if body.processing_state is None:
        raise ValueError("Estimate processing state is required")
    existing = db.scalar(select(Estimate.id).where(Estimate.source_id == body.source_id, Estimate.id != estimate.id))
    if existing:
        raise ValueError("Estimate source ID is already bound")
    estimate.source_id = body.source_id
    estimate.status = body.status
    estimate.amount_cents = body.amount_cents
    estimate.processing_state = body.processing_state
    estimate.processing_error = body.processing_error
    if body.provider_name:
        estimate.provider_name = body.provider_name
