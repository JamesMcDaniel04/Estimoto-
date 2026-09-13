"""Customer-owned maintenance contacts and explicitly reviewed outreach."""
import hashlib
import html
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from .auth import bridge_authorized, current_customer, db_session
from .models import Customer, RateBucket, Vehicle, now
from .shop_models import MyShop, ShopOutbox, ShopOutreach
from .workflow import payload_hash

router = APIRouter(prefix="/v1")
MAIL_ENDPOINT = "https://api.resend.com/emails"
MAX_MAIL_RESPONSE = 4096
ACTION_LIFETIME = timedelta(days=14)
RETRY_WINDOW = timedelta(hours=23)  # Resend dedupes for 24h; keep an hour of safety margin.
EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
PHONE_RE = re.compile(r"^\+?[0-9 ()-]{7,50}$")


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShopWrite(Strict):
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)
    vehicle_id: str | None = Field(default=None, max_length=36)

    @field_validator("name", "email", "phone", "address", "website", "notes")
    @classmethod
    def no_controls(cls, value):
        if value is not None and any(ord(char) < 32 and char not in "\t\n" for char in value):
            raise ValueError("Control characters are not accepted")
        return value


class OutreachDraftWrite(Strict):
    shop_id: str = Field(min_length=1, max_length=36)
    vehicle_id: str | None = Field(default=None, max_length=36)
    service_summary: str = Field(min_length=1, max_length=500)
    customer_message: str = Field(default="", max_length=1000)
    proposed_slots: list[datetime] = Field(min_length=1, max_length=3)

    @field_validator("service_summary", "customer_message")
    @classmethod
    def meaningful_text(cls, value):
        if any(ord(char) < 32 and char not in "\t\n" for char in value):
            raise ValueError("Control characters are not accepted")
        if not value.strip() and value:
            raise ValueError("Enter meaningful text")
        return value

    @field_validator("proposed_slots", mode="before")
    @classmethod
    def timestamp_strings(cls, values):
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("Slots must be ISO timestamps with time zones")
        return values

    @field_validator("proposed_slots")
    @classmethod
    def future_aware_slots(cls, values):
        normalized = []
        for value in values:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Slots need a time zone")
            utc = value.astimezone(timezone.utc)
            normalized.append(utc)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Slots must be distinct")
        return normalized


class AuthorizeWrite(Strict):
    share_contact: Literal[True]
    review_hash: str = Field(min_length=64, max_length=64)


def _owned_shop(db, shop_id, customer_id):
    shop = db.get(MyShop, shop_id)
    if not shop or shop.customer_id != customer_id or shop.deleted:
        raise HTTPException(404, "Shop not found.")
    return shop


def _owned_outreach(db, outreach_id, customer_id):
    outreach = db.get(ShopOutreach, outreach_id)
    if not outreach or outreach.customer_id != customer_id:
        raise HTTPException(404, "Outreach not found.")
    return outreach


def _owned_vehicle(db, vehicle_id, customer_id):
    if vehicle_id is None:
        return None
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle or vehicle.customer_id != customer_id:
        raise HTTPException(404, "Vehicle not found.")
    return vehicle


def _validate_shop(shop):
    if not shop.name.strip() or "\n" in shop.name or "\r" in shop.name:
        raise HTTPException(422, "Enter a shop name.")
    if shop.email and not EMAIL_RE.fullmatch(shop.email):
        raise HTTPException(422, "Enter a valid shop email.")
    if shop.phone and (not PHONE_RE.fullmatch(shop.phone) or len(re.sub(r"\D", "", shop.phone)) < 7):
        raise HTTPException(422, "Enter a valid shop phone number.")
    if not shop.email and not shop.phone:
        raise HTTPException(422, "Enter a shop email or phone number.")
    if shop.website:
        parsed = urlparse(shop.website)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise HTTPException(422, "Enter a valid shop website.")


def _shop_view(shop):
    return {key: getattr(shop, key) for key in (
        "id", "vehicle_id", "name", "email", "phone", "address", "website", "notes")}


def _call_link(phone):
    digits = re.sub(r"\D", "", phone)
    return "tel:" + ("+" if phone.startswith("+") else "") + digits if digits else None


def _outreach_view(outreach):
    return {"id": outreach.id, "shop_id": outreach.shop_id, "shop_name": outreach.shop_name,
            "vehicle_id": outreach.vehicle_id, "recipient_email": outreach.recipient_email,
            "recipient_phone": outreach.recipient_phone, "subject": outreach.subject,
            "message": outreach.message, "shared_contact": outreach.shared_contact,
            "vehicle_summary": outreach.vehicle_summary, "proposed_slots": outreach.proposed_slots,
            "review_hash": outreach.review_hash, "status": outreach.status,
            "delivery_status": outreach.delivery_status,
            "call_link": _call_link(outreach.recipient_phone) if outreach.status == "call_required" else None,
            "confirmed_slot": outreach.confirmed_slot,
            "created_at": outreach.created_at.isoformat(), "updated_at": outreach.updated_at.isoformat()}


def _lock_customer(db, customer_id):
    db.execute(update(Customer).where(Customer.id == customer_id).values(id=Customer.id))
    db.expire_all()


def _consume_rate(db, customer_id, action, limit):
    bucket = int(now().timestamp() // 3600)
    row = db.get(RateBucket, (customer_id, action, bucket))
    if row and row.count >= limit:
        raise HTTPException(429, "Too many shop requests. Please try later.")
    if row:
        row.count += 1
    else:
        db.add(RateBucket(customer_id=customer_id, action=action, hour_bucket=bucket, count=1))


def _lock_outreach(db, outreach_id):
    db.execute(update(ShopOutreach).where(ShopOutreach.id == outreach_id)
               .values(updated_at=ShopOutreach.updated_at))
    db.expire_all()


@router.get("/my-shops")
def list_shops(c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    rows = db.scalars(select(MyShop).where(MyShop.customer_id == c.id, MyShop.deleted.is_(False))
                      .order_by(MyShop.created_at, MyShop.id)).all()
    return [_shop_view(row) for row in rows]


@router.post("/my-shops", status_code=201)
def create_shop(body: ShopWrite, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    data = body.model_dump(exclude_unset=True)
    if body.name is None or body.email is None or body.phone is None or body.address is None:
        raise HTTPException(422, "Name, email, phone, and address fields are required; email or phone may be blank.")
    _owned_vehicle(db, body.vehicle_id, c.id)
    _lock_customer(db, c.id)
    if db.scalar(select(MyShop.id).where(MyShop.customer_id == c.id, MyShop.deleted.is_(False)).limit(50).offset(49)):
        raise HTTPException(429, "Saved shop limit reached.")
    shop = MyShop(customer_id=c.id, **data)
    _validate_shop(shop)
    db.add(shop)
    db.commit()
    return _shop_view(shop)


@router.put("/my-shops/{shop_id}")
def update_shop(shop_id: str, body: ShopWrite, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    shop = _owned_shop(db, shop_id, c.id)
    if body.vehicle_id is not None or "vehicle_id" in body.model_fields_set:
        _owned_vehicle(db, body.vehicle_id, c.id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None and key != "vehicle_id":
            raise HTTPException(422, "Shop fields cannot be null.")
        setattr(shop, key, value)
    _validate_shop(shop)
    db.commit()
    return _shop_view(shop)


@router.delete("/my-shops/{shop_id}")
def delete_shop(shop_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    shop = _owned_shop(db, shop_id, c.id)
    shop.deleted = True
    db.commit()
    return {"deleted": True}


@router.get("/shop-outreach")
def list_outreach(c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    rows = db.scalars(select(ShopOutreach).where(ShopOutreach.customer_id == c.id)
                      .order_by(ShopOutreach.created_at.desc(), ShopOutreach.id.desc()).limit(100)).all()
    return [_outreach_view(row) for row in rows]


@router.get("/shop-outreach/{outreach_id}")
def get_outreach(outreach_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    return _outreach_view(_owned_outreach(db, outreach_id, c.id))


@router.post("/shop-outreach", status_code=201)
def create_outreach(body: OutreachDraftWrite, idempotency_key: str | None = Header(default=None),
                    c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(422, "Idempotency-Key is required.")
    creation_hash = payload_hash(body.model_dump(mode="json"))
    _lock_customer(db, c.id)
    existing = db.scalar(select(ShopOutreach).where(ShopOutreach.customer_id == c.id,
                                                    ShopOutreach.creation_key == idempotency_key))
    if existing:
        if existing.creation_hash != creation_hash:
            raise HTTPException(409, "This draft key was used for different details.")
        return _outreach_view(existing)
    _consume_rate(db, c.id, "shop_draft", 10)
    current = now()
    if any(not current + timedelta(hours=1) < value <= current + timedelta(days=90)
           for value in body.proposed_slots):
        raise HTTPException(422, "Slots must be between one hour and 90 days ahead.")
    shop = _owned_shop(db, body.shop_id, c.id)
    vehicle_id = body.vehicle_id or shop.vehicle_id
    vehicle = _owned_vehicle(db, vehicle_id, c.id)
    if not c.name.strip() or not EMAIL_RE.fullmatch(c.email) or c.phone and not PHONE_RE.fullmatch(c.phone):
        raise HTTPException(422, "Save a valid contact name, email, and optional phone before outreach.")
    vehicle_summary = f"{vehicle.year} {vehicle.make} {vehicle.model}" if vehicle else ""
    slots = [value.isoformat() for value in body.proposed_slots]
    message = (f"Service request: {body.service_summary.strip()}\n"
               + (f"Vehicle: {vehicle_summary}\n" if vehicle_summary else "")
               + (f"Customer note: {body.customer_message.strip()}\n" if body.customer_message.strip() else "")
               + "Suggested appointment times (UTC):\n" + "\n".join(f"- {value}" for value in slots)
               + "\nPlease confirm one offered time using the secure link in this email. "
                 "This request is not a booked appointment until you confirm.")
    review = {"shop_name": shop.name, "recipient_email": shop.email, "recipient_phone": shop.phone,
              "subject": "Service availability request from Estimoto +", "message": message,
              "shared_contact": {"name": c.name, "email": c.email, "phone": c.phone},
              "vehicle_summary": vehicle_summary, "proposed_slots": slots}
    outreach = ShopOutreach(customer_id=c.id, shop_id=shop.id, vehicle_id=vehicle_id,
                            creation_key=idempotency_key, creation_hash=creation_hash,
                            review_hash=payload_hash(review), **review)
    db.add(outreach)
    db.commit()
    return _outreach_view(outreach)


def _mail_config():
    key = os.getenv("RESEND_API_KEY", "")
    sender = os.getenv("EMAIL_FROM", "")
    base = os.getenv("SHOP_ACTION_BASE_URL", "")
    parsed = urlparse(base)
    if not key or not sender or "\n" in sender or "\r" in sender or not EMAIL_RE.search(sender.split("<")[-1].rstrip(">")):
        return None
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
        return None
    return key, sender, base.rstrip("/")


@router.post("/shop-outreach/{outreach_id}/authorize")
def authorize_outreach(outreach_id: str, body: AuthorizeWrite, request: Request,
                       idempotency_key: str | None = Header(default=None),
                       c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    if not idempotency_key or len(idempotency_key) > 200 or not body.share_contact:
        raise HTTPException(422, "Explicit contact sharing and Idempotency-Key are required.")
    _lock_customer(db, c.id)
    _owned_outreach(db, outreach_id, c.id)
    _lock_outreach(db, outreach_id)
    outreach = _owned_outreach(db, outreach_id, c.id)
    if body.review_hash != outreach.review_hash:
        raise HTTPException(409, "The reviewed outreach details changed.")
    authorization_hash = payload_hash(body.model_dump())
    if outreach.status != "draft":
        if outreach.authorized_key == idempotency_key and outreach.authorized_hash == authorization_hash:
            return _outreach_view(outreach)
        raise HTTPException(409, "Outreach was already authorized with another operation.")
    if any(datetime.fromisoformat(value) <= now() + timedelta(hours=1) for value in outreach.proposed_slots):
        raise HTTPException(422, "An offered time is too soon or has passed. Create a new draft.")
    _consume_rate(db, c.id, "shop_authorize", 10)
    if outreach.recipient_email:
        mail = _mail_config()
        if c.demo or mail is None:
            raise HTTPException(503, "Shop email outreach is unavailable right now.")
        _, sender, base = mail
        token = secrets.token_urlsafe(32)
        outreach.action_token_hash = hashlib.sha256(token.encode()).hexdigest()
        outreach.action_expires_at = now() + ACTION_LIFETIME
        link = f"{base}/v1/shop-actions/{token}"
        text = (f"Hello {outreach.shop_name},\n\n{outreach.message}\n\n"
                f"Confirm one offered time: {link}\n\n"
                f"Customer contact (shared with permission): {outreach.shared_contact['name']}, "
                f"{outreach.shared_contact['email']}, {outreach.shared_contact['phone']}\n")
        payload = {"from": sender, "to": [outreach.recipient_email],
                   "subject": outreach.subject, "text": text}
        db.add(ShopOutbox(outreach_id=outreach.id, payload=payload, payload_hash=payload_hash(payload)))
        outreach.status = "queued"
        outreach.delivery_status = "queued"
    else:
        outreach.status = "call_required"
        outreach.delivery_status = "not_sent"
    outreach.authorized_key = idempotency_key
    outreach.authorized_hash = authorization_hash
    outreach.updated_at = now()
    db.commit()
    return _outreach_view(outreach)


def _action_record(db, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{30,100}", token):
        raise HTTPException(404, "Action link not found.")
    record = db.scalar(select(ShopOutreach).where(
        ShopOutreach.action_token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if not record or not record.action_expires_at or _utc(record.action_expires_at) <= now():
        raise HTTPException(404, "Action link expired or unavailable.")
    return record


@router.get("/shop-actions/{token}", response_class=HTMLResponse)
def shop_action_landing(token: str, db: Session = Depends(db_session)):
    record = _action_record(db, token)
    if record.status not in {"waiting_for_reply", "delivery_unknown", "confirmed"}:
        raise HTTPException(404, "Action link not available.")
    options = "".join(f'<label><input type="radio" name="slot" value="{html.escape(value, quote=True)}" required> '
                      f'{html.escape(value)}</label><br>' for value in record.proposed_slots)
    page = ("<!doctype html><html><head><meta name='referrer' content='no-referrer'>"
            "<title>Confirm availability</title></head><body><h1>Confirm an offered time</h1>"
            "<p>This is a request for availability. Choose only a time you can honor.</p>"
            f'<form method="post" action="/v1/shop-actions/{html.escape(token, quote=True)}">'
            f"{options}<button type='submit'>Confirm this time</button></form></body></html>")
    return HTMLResponse(page, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                       "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"})


@router.post("/shop-actions/{token}", response_class=HTMLResponse)
async def confirm_shop_slot(token: str, request: Request, db: Session = Depends(db_session)):
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Use the confirmation form.")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024:
            raise HTTPException(413, "Confirmation is too large.")
    try:
        fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(422, "Choose an offered time.")
    if set(fields) != {"slot"} or len(fields["slot"]) != 1 or len(fields["slot"][0]) > 40:
        raise HTTPException(422, "Choose an offered time.")
    slot = fields["slot"][0]
    record = _action_record(db, token)
    _lock_outreach(db, record.id)
    record = _action_record(db, token)
    if slot not in record.proposed_slots:
        raise HTTPException(422, "Choose an offered time.")
    if record.status == "confirmed":
        if record.confirmed_slot != slot:
            raise HTTPException(409, "A different time was already confirmed.")
    elif record.status not in {"waiting_for_reply", "delivery_unknown"}:
        raise HTTPException(409, "This request cannot be confirmed yet.")
    else:
        if datetime.fromisoformat(slot) <= now():
            raise HTTPException(422, "That offered time has passed.")
        record.status = "confirmed"
        record.confirmed_slot = slot
        record.updated_at = now()
        db.commit()
    return HTMLResponse("<!doctype html><html><body><h1>Time confirmed</h1><p>The customer can now see the confirmed time.</p></body></html>",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def _claim_mail(db, outbox_id):
    outreach_id = db.scalar(select(ShopOutbox.outreach_id).where(ShopOutbox.id == outbox_id))
    db.rollback()
    if not outreach_id:
        return None
    _lock_outreach(db, outreach_id)
    outreach = db.get(ShopOutreach, outreach_id)
    item = db.get(ShopOutbox, outbox_id)
    current = now()
    if not item or item.finished_at or _utc(item.next_attempt_at) > current or item.claim_token and item.lease_until and _utc(item.lease_until) > current:
        db.rollback()
        return None
    if (not outreach or outreach.status != "queued" or outreach.delivery_status not in {"queued", "retrying"} or
            not isinstance(item.payload, dict) or item.payload_hash != payload_hash(item.payload) or
            item.payload.get("to") != [outreach.recipient_email] or
            _mail_config() is None):
        if outreach:
            outreach.delivery_status = "delivery_failed"
            outreach.status = "delivery_failed"
        item.finished_at = current
        db.commit()
        return "failed"
    if item.first_attempt_at and current >= _utc(item.first_attempt_at) + RETRY_WINDOW:
        outreach.delivery_status = "delivery_unknown"
        outreach.status = "delivery_unknown"
        item.finished_at = current
        db.commit()
        return "unknown"
    token = str(uuid4())
    first_attempt_at = _utc(item.first_attempt_at) or current
    claimed = db.execute(update(ShopOutbox).where(
        ShopOutbox.id == outbox_id, ShopOutbox.finished_at.is_(None), ShopOutbox.next_attempt_at <= current,
        or_(ShopOutbox.claim_token.is_(None), ShopOutbox.lease_until <= current))
        .values(claim_token=token, lease_until=current + timedelta(seconds=60),
                attempts=ShopOutbox.attempts + 1,
                first_attempt_at=first_attempt_at)
        .returning(ShopOutbox.id).execution_options(synchronize_session=False)).first()
    if not claimed:
        db.rollback()
        return None
    payload = item.payload
    db.commit()
    return token, outreach_id, payload, first_attempt_at


def _send_mail(payload, outreach_id, first_attempt_at, transport, api_url):
    if now() + timedelta(seconds=15) >= first_attempt_at + RETRY_WINDOW:
        return "unknown", None
    mail = _mail_config()
    if mail is None:
        return "retry", None
    key = mail[0]
    try:
        with httpx.Client(timeout=10, transport=transport, follow_redirects=False) as client:
            with client.stream("POST", api_url, json=payload, headers={
                "Authorization": f"Bearer {key}", "Idempotency-Key": f"shop-outreach:{outreach_id}"}) as response:
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=1024):
                    raw.extend(chunk)
                    if len(raw) > MAX_MAIL_RESPONSE:
                        return "retry", None
                status = response.status_code
        decoded = json.loads(raw) if raw else {}
    except (httpx.HTTPError, ValueError, UnicodeDecodeError):
        return "retry", None
    if status in {200, 201, 202} and isinstance(decoded, dict):
        receipt = decoded.get("id")
        if isinstance(receipt, str) and 0 < len(receipt) <= 200:
            return "delivered", receipt
    if status in {400, 401, 403, 404, 422}:
        return "failed", None
    if status == 409 and isinstance(decoded, dict) and decoded.get("name") == "invalid_idempotent_request":
        return "failed", None
    return "retry", None


def _finish_mail(db, outbox_id, token, outreach_id, outcome, receipt):
    _lock_outreach(db, outreach_id)
    item = db.get(ShopOutbox, outbox_id)
    outreach = db.get(ShopOutreach, outreach_id)
    if not item or item.claim_token != token or not outreach or item.finished_at:
        db.rollback()
        return None
    current = now()
    if outcome == "delivered":
        item.provider_id = receipt
        item.finished_at = current
        outreach.status = "waiting_for_reply"
        outreach.delivery_status = "delivered"
    elif outcome == "failed":
        item.finished_at = current
        outreach.status = "delivery_failed"
        outreach.delivery_status = "delivery_failed"
    elif outcome == "unknown":
        item.finished_at = current
        outreach.status = "delivery_unknown"
        outreach.delivery_status = "delivery_unknown"
    else:
        item.next_attempt_at = current + timedelta(seconds=min(1800, 2 ** min(item.attempts, 10)))
        outreach.delivery_status = "retrying"
    item.claim_token = None
    item.lease_until = None
    outreach.updated_at = current
    db.commit()
    return outcome


def deliver_shop_batch(session_factory, transport=None, *, api_url=MAIL_ENDPOINT):
    with session_factory() as db:
        ids = db.scalars(select(ShopOutbox.id).where(
            ShopOutbox.finished_at.is_(None), ShopOutbox.next_attempt_at <= now(),
            or_(ShopOutbox.claim_token.is_(None), ShopOutbox.lease_until <= now()))
            .order_by(ShopOutbox.next_attempt_at, ShopOutbox.id).limit(20)).all()
    delivered = failed = unknown = 0
    for outbox_id in ids:
        with session_factory() as db:
            claim = _claim_mail(db, outbox_id)
        if claim is None:
            continue
        if claim == "failed":
            failed += 1
            continue
        if claim == "unknown":
            unknown += 1
            continue
        token, outreach_id, payload, first_attempt_at = claim
        outcome, receipt = _send_mail(payload, outreach_id, first_attempt_at, transport, api_url)
        with session_factory() as db:
            result = _finish_mail(db, outbox_id, token, outreach_id, outcome, receipt)
        if result == "delivered":
            delivered += 1
        elif result == "failed":
            failed += 1
        elif result == "unknown":
            unknown += 1
    return {"delivered": delivered, "failed": failed, "unknown": unknown}


@router.post("/bridge/shop-outreach/deliver", dependencies=[Depends(bridge_authorized)])
def deliver_shop_outreach(request: Request):
    url = (os.getenv("RESEND_API_URL", MAIL_ENDPOINT) if request.app.state.settings.environment != "production" else MAIL_ENDPOINT)
    return deliver_shop_batch(request.app.state.session_factory,
                              getattr(request.app.state, "shop_mail_transport", None), api_url=url)
