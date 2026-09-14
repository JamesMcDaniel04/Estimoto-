"""Bounded authoritative provider catalog and request lifecycle pulls."""
import json
import logging
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update

from .models import Outbox, Provider, ServiceRequest, now
from .schemas import ProviderPublish, RequestInboundEvent
from .partner_media import valid_partner_media

LOG = logging.getLogger(__name__)
MAX_CATALOG_BYTES = 1024 * 1024
MAX_STATUS_BYTES = 64 * 1024


def _read_json(settings, transport, url, limit):
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            with client.stream("GET", url, headers={"X-Bridge-Key": settings.bridge_key}) as response:
                if response.status_code != 200:
                    return None
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=4096):
                    raw.extend(chunk)
                    if len(raw) > limit:
                        return None
        return json.loads(raw)
    except (httpx.HTTPError, ValueError, UnicodeDecodeError):
        return None


def sync_providers(settings, transport, session_factory):
    if not settings.bridge_url or not settings.bridge_key:
        return False
    parsed = urlparse(settings.bridge_url)
    if not parsed.path.endswith("/requests"):
        return False
    url = settings.bridge_url[:-len("requests")] + "providers"
    data = _read_json(settings, transport, url, MAX_CATALOG_BYTES)
    if not isinstance(data, list) or len(data) > 1000:
        return False
    try:
        published = [ProviderPublish.model_validate(item) for item in data]
    except ValidationError:
        return False
    if len({item.source_id for item in published}) != len(published):
        return False
    if any(not valid_partner_media(item.media, source_id=item.source_id, name=item.name,
                                   bridge_url=settings.bridge_url) for item in published):
        return False
    with session_factory() as db:
        source_ids = [item.source_id for item in published]
        db.execute(update(Provider).where(Provider.demo_only.is_(False),
                                          ~Provider.source_id.in_(source_ids))
                   .values(public_visible=False, accepting_requests=False))
        for body in published:
            existing = db.scalar(select(Provider).where(Provider.source_id == body.source_id).with_for_update())
            if existing and existing.demo_only:
                db.rollback()
                return False
            if not existing:
                existing = Provider(source_id=body.source_id)
                db.add(existing)
            for key, value in body.model_dump().items():
                setattr(existing, key, value)
        db.commit()
    return True


def sync_request_statuses(settings, transport, session_factory):
    if not settings.bridge_url or not settings.bridge_key:
        return {"updated": 0, "failed": 0}
    with session_factory() as db:
        ids = db.scalars(select(ServiceRequest.id).where(
            ServiceRequest.delivery_status == "delivered",
            ServiceRequest.status.in_(("requested", "accepted", "scheduled")),
        ).order_by(ServiceRequest.last_status_poll_at.is_not(None),
                   ServiceRequest.last_status_poll_at, ServiceRequest.id).limit(20)).all()
    updated = failed = 0
    for request_id in ids:
        data = _read_json(settings, transport, settings.bridge_url.rstrip("/") + "/" + request_id, MAX_STATUS_BYTES)
        with session_factory() as db:
            request = db.get(ServiceRequest, request_id)
            provider = db.get(Provider, request.provider_id) if request else None
            creation = db.scalar(select(Outbox).where(Outbox.request_id == request_id, Outbox.kind == "create"))
            trusted = (isinstance(data, dict) and request is not None and provider is not None and creation is not None and
                       bool(creation.receipt_id) and
                       data.get("request_id") == request_id and data.get("provider_source_id") == provider.source_id and
                       data.get("receipt_id") == creation.receipt_id and isinstance(data.get("events"), list) and
                       len(data["events"]) <= 100)
            db.execute(update(ServiceRequest).where(ServiceRequest.id == request_id)
                       .values(last_status_poll_at=now()))
            db.commit()
        if not trusted:
            failed += 1
            continue
        from .bridge import inbound_event
        applied = True
        for item in data["events"]:
            if not isinstance(item, dict):
                applied = False
                break
            if item.get("status") == "requested":
                continue
            try:
                body = RequestInboundEvent.model_validate({
                    "event_id": item.get("event_id"), "provider_id": provider.id,
                    "status": item.get("status"), "message": item.get("message", ""),
                    "scheduled_at": item.get("scheduled_at"),
                })
                with session_factory() as db:
                    inbound_event(request_id, body, db)
            except (ValidationError, HTTPException, ValueError):
                applied = False
                break
        if applied:
            updated += 1
        else:
            LOG.warning("Plus request status event could not be applied")
            failed += 1
    return {"updated": updated, "failed": failed}


def sync_bridge(settings, transport, session_factory):
    return {"providers_synced": sync_providers(settings, transport, session_factory),
            **sync_request_statuses(settings, transport, session_factory)}
