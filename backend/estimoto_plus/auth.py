import base64
import hashlib
import hmac
from http.cookiejar import CookieJar, DefaultCookiePolicy
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


class _NoAuthCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False


def create_auth_client():
    """One thread-safe client per app; its lifespan owner closes the pool."""
    return httpx.Client(timeout=httpx.Timeout(5, connect=3, pool=2),
                        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10,
                                            keepalive_expiry=30),
                        cookies=CookieJar(policy=_NoAuthCookies()),
                        follow_redirects=False, trust_env=False)


def verify_supabase(settings: Settings, token: str, client: httpx.Client | None = None):
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(503, "Sign-in is unavailable. Please try again later.")
    url = settings.supabase_url.rstrip("/") + "/auth/v1/user"
    try:
        if client is None:
            with create_auth_client() as local:
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
        if verifier:
            identity = verifier(token)
        else:
            def upstream():
                return verify_supabase(settings, token, request.app.state.auth_client)
            cache = getattr(request.app.state, 'auth_cache', None)
            identity = (cache.verify(token, upstream, read_only=request.method in {'GET', 'HEAD'})
                        if cache is not None else upstream())
    if not isinstance(identity, dict) or not identity.get("id") or not identity.get("email") or not (identity.get("email_confirmed_at") or identity.get("confirmed_at")) or identity.get("is_anonymous"):
        raise HTTPException(401, "Sign in to continue.")
    customer_id, email = str(identity["id"]), str(identity["email"])
    if len(customer_id) > 100 or len(email) > 320:
        raise HTTPException(401, "Sign in to continue.")
    customer = db.get(Customer, customer_id)
    if customer is None:
        # Concurrent first API calls must converge on one account without
        # overwriting profile fields that another request has already saved.
        if db.get_bind().dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        db.execute(insert(Customer).values(id=customer_id, email=email,
                                           demo=bool(identity.get("_demo")))
                   .on_conflict_do_nothing(index_elements=[Customer.id]))
        db.commit()
        customer = db.get(Customer, customer_id)
    if customer.email != email:
        customer.email = email
        db.commit()
    return customer


def bridge_authorized(request: Request, x_bridge_key: str | None = Header(default=None)):
    key = request.app.state.settings.bridge_key
    if not key:
        raise HTTPException(503, "Bridge is unavailable.")
    if not x_bridge_key or not hmac.compare_digest(x_bridge_key, key):
        raise HTTPException(401, "Bridge authentication required.")
