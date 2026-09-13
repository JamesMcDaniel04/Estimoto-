import base64
import hashlib
import hmac
import json
import time

import httpx
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .config import Settings
from .models import Customer


def dev_allowed(settings: Settings) -> bool:
    return settings.environment in {"development", "demo"} and settings.dev_sessions_enabled and len(settings.dev_token_secret) >= 32


def make_dev_token(settings: Settings) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "demo-customer", "exp": int(time.time()) + 86400}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(settings.dev_token_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"dev.{payload}.{signature}"


def verify_dev_token(settings: Settings, token: str):
    if not dev_allowed(settings):
        return None
    try:
        prefix, payload, signature = token.split(".")
        expected = hmac.new(settings.dev_token_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if prefix != "dev" or not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data.get("sub") != "demo-customer" or data.get("exp", 0) <= time.time():
            return None
        return {"id": "demo-customer", "email": "demo@example.test", "email_confirmed_at": "demo", "_demo": True}
    except (ValueError, KeyError, TypeError):
        return None


def verify_supabase(settings: Settings, token: str, client: httpx.Client | None = None):
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(503, "Sign-in is unavailable. Please try again later.")
    url = settings.supabase_url.rstrip("/") + "/auth/v1/user"
    try:
        if client is None:
            with httpx.Client(timeout=5) as local:
                response = local.get(url, headers={"apikey": settings.supabase_publishable_key, "Authorization": f"Bearer {token}"})
        else:
            response = client.get(url, headers={"apikey": settings.supabase_publishable_key, "Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        raise HTTPException(503, "Sign-in is unavailable. Please try again later.")
    if response.status_code in {400, 401, 403}:
        raise HTTPException(401, "Sign in to continue.")
    if response.status_code != 200:
        raise HTTPException(503, "Sign-in is unavailable. Please try again later.")
    try:
        identity = response.json()
    except ValueError:
        raise HTTPException(503, "Sign-in is unavailable. Please try again later.")
    if not isinstance(identity, dict):
        raise HTTPException(503, "Sign-in is unavailable. Please try again later.")
    return identity


def db_session(request: Request):
    with request.app.state.session_factory() as session:
        yield session


def current_customer(request: Request, authorization: str | None = Header(default=None), db: Session = Depends(db_session)):
    if not authorization or not authorization.startswith("Bearer ") or not authorization[7:]:
        raise HTTPException(401, "Sign in to continue.")
    token = authorization[7:]
    settings = request.app.state.settings
    identity = verify_dev_token(settings, token) if token.startswith("dev.") else None
    if identity is None:
        if token.startswith("dev."):
            raise HTTPException(401, "Sign in to continue.")
        verifier = request.app.state.auth_verifier
        identity = verifier(token) if verifier else verify_supabase(settings, token, request.app.state.auth_client)
    if not isinstance(identity, dict) or not identity.get("id") or not identity.get("email") or not (identity.get("email_confirmed_at") or identity.get("confirmed_at")) or identity.get("is_anonymous"):
        raise HTTPException(401, "Sign in to continue.")
    customer = db.get(Customer, str(identity["id"]))
    if customer is None:
        customer = Customer(id=str(identity["id"]), email=str(identity["email"]), demo=bool(identity.get("_demo")))
        db.add(customer)
    else:
        customer.email = str(identity["email"])
    db.commit()
    return customer


def bridge_authorized(request: Request, x_bridge_key: str | None = Header(default=None)):
    key = request.app.state.settings.bridge_key
    if not key:
        raise HTTPException(503, "Bridge is unavailable.")
    if not x_bridge_key or not hmac.compare_digest(x_bridge_key, key):
        raise HTTPException(401, "Bridge authentication required.")
