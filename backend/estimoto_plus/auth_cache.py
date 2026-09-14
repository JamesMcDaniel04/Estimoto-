"""Per-app cache of upstream-verified identities for GET/HEAD authentication.

Reads can observe Supabase revocation up to 15 seconds after verification starts,
never beyond JWT expiry. Writes always verify upstream and invalidate reads.
JWT parsing only bounds cache lifetime; it never authenticates a token locally.
Raw bearer tokens, user metadata, errors and negative results are not retained.
"""
import base64
from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from threading import Event, Lock
from time import monotonic, time as wall_time


READ_TTL_SECONDS = 15
MAX_ENTRIES = 1024
MAX_PENDING = 64
MAX_TOKEN_CHARS = 16384
FLIGHT_WAIT_SECONDS = 6


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JWT claim')
        value[key] = item
    return value


def _jwt_bounds(token):
    """Return expiry/subject only for bounded, structurally valid signed JWTs."""
    if not isinstance(token, str) or not 1 <= len(token) <= MAX_TOKEN_CHARS:
        return None
    try:
        pieces = token.split('.')
        if len(pieces) != 3 or any(not re.fullmatch(r'[A-Za-z0-9_-]+', p) for p in pieces):
            return None
        decoded = [base64.b64decode(p + '=' * (-len(p) % 4), altchars=b'-_', validate=True)
                   for p in pieces]
        header, claims = [json.loads(p, object_pairs_hook=_unique_object) for p in decoded[:2]]
        if (not isinstance(header, dict) or not isinstance(claims, dict) or
                not isinstance(header.get('alg'), str) or not header['alg'] or
                header['alg'].casefold() == 'none' or not decoded[2]):
            return None
        expiry, subject = claims.get('exp'), claims.get('sub')
        if (isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or
                not math.isfinite(expiry) or not isinstance(subject, str) or
                not 1 <= len(subject) <= 100):
            return None
        return expiry, subject
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        return None


def _cache_identity(identity, subject):
    if not isinstance(identity, dict):
        return None
    user_id, email = identity.get('id'), identity.get('email')
    if (not isinstance(user_id, str) or user_id != subject or
            not isinstance(email, str) or not 1 <= len(email) <= 320 or
            not (identity.get('email_confirmed_at') or identity.get('confirmed_at')) or
            identity.get('is_anonymous') or identity.get('_demo')):
        return None
    # All downstream auth needs is this confirmed identity. In particular,
    # mutable user metadata and upstream response objects never enter the cache.
    return {'id': user_id, 'email': email, 'confirmed_at': True}


@dataclass
class _Entry:
    identity: dict
    deadline: float
    jwt_expiry: float


@dataclass
class _Flight:
    started: float
    done: Event = field(default_factory=Event)
    invalidated: bool = False


class VerifiedAuthCache:
    def __init__(self, *, max_entries=MAX_ENTRIES, max_pending=MAX_PENDING):
        self._max_entries = max(1, min(MAX_ENTRIES, max_entries))
        self._max_pending = max(1, min(MAX_PENDING, max_pending))
        self._entries = OrderedDict()
        self._pending = {}
        self._lock = Lock()

    @staticmethod
    def _key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def _cached(self, key):
        # Caller holds the lock. Monotonic time prevents clock rollback from
        # extending TTL; wall time independently enforces JWT's absolute expiry.
        entry = self._entries.get(key)
        if entry is None:
            return None
        if monotonic() >= entry.deadline or wall_time() >= entry.jwt_expiry:
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return dict(entry.identity)

    def invalidate(self, token):
        key = self._key(token)
        with self._lock:
            self._entries.pop(key, None)
            if flight := self._pending.get(key):
                flight.invalidated = True

    def clear(self):
        with self._lock:
            self._entries.clear()
            for flight in self._pending.values():
                flight.invalidated = True

    def verify(self, token, loader, *, read_only):
        """Call loader to authenticate; reuse only a still-current positive read."""
        if not read_only:
            self.invalidate(token)
            try:
                return loader()
            finally:
                # Also cancel reads that started during this fresh verification.
                self.invalidate(token)

        bounds = _jwt_bounds(token)
        if bounds is None or bounds[0] <= wall_time():
            return loader()  # Opaque/malformed tokens still get upstream auth.
        expiry, subject = bounds
        key = self._key(token)
        with self._lock:
            if cached := self._cached(key):
                return cached
            flight = self._pending.get(key)
            owner = flight is None and len(self._pending) < self._max_pending
            if owner:
                flight = self._pending[key] = _Flight(monotonic())
        if not owner:
            if flight is not None and flight.done.wait(FLIGHT_WAIT_SECONDS):
                with self._lock:
                    if cached := self._cached(key):
                        return cached
            # Errors are never cached. A failed/expired/cancelled flight or a
            # full pending pool falls back to fresh auth without adding state.
            return loader()

        try:
            identity = loader()
            confirmed = _cache_identity(identity, subject)
            with self._lock:
                deadline = flight.started + READ_TTL_SECONDS
                if (confirmed is not None and not flight.invalidated and
                        monotonic() < deadline and wall_time() < expiry):
                    while len(self._entries) >= self._max_entries:
                        self._entries.popitem(last=False)
                    self._entries[key] = _Entry(confirmed, deadline, expiry)
            return identity
        finally:
            with self._lock:
                self._pending.pop(key, None)
                flight.done.set()
