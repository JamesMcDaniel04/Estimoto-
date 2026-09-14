"""Shared bounded public cache; DB claims serialize upstream calls across workers."""
from datetime import timedelta
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from .calendar_scheduling import utc
from .discovery_models import DirectoryBudget, DirectoryCache, PublicListing
from .discovery_provider import DirectoryUnavailable, fetch_listings, fetch_zip, distance_miles, RADIUS_MILES
from .models import now, uid

FRESH = timedelta(days=1)
STALE = timedelta(days=7)
MAX_CACHE = 128
MAX_LISTINGS = 20000


def cached(factory, key, fetch, *, budget=None, allow_fetch=True):
    current = now()
    reservation = 0
    meter = {'body_bytes': 0}
    budget_day = current.date().isoformat()
    with factory() as db:
        row = db.get(DirectoryCache, key)
        previous = row.value if row and row.fetched_at and utc(row.fetched_at) >= current - STALE else None
        checked = utc(row.fetched_at) if previous is not None else None
        if checked and checked >= current - FRESH:
            return previous, 'ready', checked
        if not allow_fetch or (row and utc(row.next_attempt_at) > current):
            return previous, 'stale' if previous is not None else 'unavailable', checked
        gate_key = 'gate:' + key.split(':')[0]
        if not db.get(DirectoryCache, gate_key):
            try:
                with db.begin_nested():
                    db.add(DirectoryCache(key=gate_key, value={}))
                    db.flush()
            except IntegrityError:
                pass
        token = uid()
        claimed = db.execute(update(DirectoryCache).where(DirectoryCache.key == gate_key,
            or_(DirectoryCache.claim_token.is_(None), DirectoryCache.lease_until <= current)).values(
                claim_token=token, lease_until=current + timedelta(seconds=40))).rowcount
        if not claimed:
            db.rollback()
            return previous, 'stale' if previous is not None else 'unavailable', checked
        # Re-read after acquiring the cross-worker gate; another worker may have filled it.
        db.expire_all()
        row = db.get(DirectoryCache, key)
        if row and row.fetched_at and utc(row.fetched_at) >= current - FRESH:
            db.execute(update(DirectoryCache).where(DirectoryCache.key == gate_key).values(claim_token=None, lease_until=None))
            db.commit()
            return row.value, 'ready', utc(row.fetched_at)
        if row and utc(row.next_attempt_at) > current:
            db.execute(update(DirectoryCache).where(DirectoryCache.key == gate_key).values(claim_token=None, lease_until=None))
            db.commit()
            return previous, 'stale' if previous is not None else 'unavailable', checked
        if budget is not None:
            daily = db.get(DirectoryBudget, budget_day)
            if daily is None:
                daily = DirectoryBudget(day=budget_day, attempts=0, body_bytes=0)
                db.add(daily)
            request_limit = max(0, min(100, budget.discovery_daily_requests))
            byte_limit = max(0, min(10_000_000, budget.discovery_daily_bytes))
            reservation = min(3 * 1024 * 1024, byte_limit - daily.body_bytes) // 1024 * 1024
            if daily.attempts >= request_limit or reservation < 1024:
                db.execute(update(DirectoryCache).where(DirectoryCache.key == gate_key).values(claim_token=None, lease_until=None))
                db.commit()
                return previous, 'stale' if previous is not None else 'unavailable', checked
            # Reserve before I/O. A process crash keeps its bytes charged; no
            # worker can spend the same daily allowance while this call runs.
            daily.attempts += 1
            daily.body_bytes += reservation
            db.execute(delete(DirectoryBudget).where(DirectoryBudget.day < (current - timedelta(days=14)).date().isoformat()))
        if not row:
            count = db.scalar(select(func.count()).select_from(DirectoryCache))
            if count >= MAX_CACHE:
                victims = db.scalars(select(DirectoryCache.key).where(~DirectoryCache.key.like('gate:%'),
                    or_(DirectoryCache.claim_token.is_(None), DirectoryCache.lease_until <= current)).order_by(DirectoryCache.fetched_at, DirectoryCache.key).limit(count - MAX_CACHE + 1)).all()
                if victims:
                    db.execute(delete(DirectoryCache).where(DirectoryCache.key.in_(victims)))
            row = DirectoryCache(key=key, value={})
            db.add(row)
        row.claim_token, row.lease_until = token, current + timedelta(seconds=40)
        db.commit()
    value = None
    try:
        value = fetch(reservation, meter) if budget is not None else fetch()
    except DirectoryUnavailable:
        value = None
    finally:
        with factory() as db:
            if reservation:
                refund = max(0, reservation - meter['body_bytes'])
                db.execute(update(DirectoryBudget).where(DirectoryBudget.day == budget_day).values(
                    body_bytes=DirectoryBudget.body_bytes - refund))
            gate = db.get(DirectoryCache, gate_key)
            row = db.get(DirectoryCache, key)
            if gate and gate.claim_token == token:
                gate.claim_token, gate.lease_until = None, None
            if row and row.claim_token == token:
                row.claim_token, row.lease_until = None, None
                row.next_attempt_at = now() + (FRESH if value is not None else timedelta(minutes=5))
                if value is not None:
                    row.value, row.fetched_at = value, now()
                    for listing in value.get('listings', []):
                        item = db.get(PublicListing, listing['source_id'])
                        if item is None:
                            item = PublicListing(source_id=listing['source_id'], value=listing)
                            db.add(item)
                        item.value, item.fetched_at = listing, now()
                    db.flush()
                    excess = db.scalar(select(func.count()).select_from(PublicListing)) - MAX_LISTINGS
                    if excess > 0:
                        victims = db.scalars(select(PublicListing.source_id).order_by(PublicListing.fetched_at, PublicListing.source_id).limit(excess)).all()
                        db.execute(delete(PublicListing).where(PublicListing.source_id.in_(victims)))
            db.commit()
    return (value, 'ready', now()) if value is not None else (previous, 'stale' if previous is not None else 'unavailable', checked)


def zip_location(factory, transport, postal, *, allow_fetch=True):
    return cached(factory, 'zip:' + postal, lambda: fetch_zip(postal, transport), allow_fetch=allow_fetch)


def public_directory(factory, transport, postal, point, settings):
    result = cached(factory, 'osm:' + postal,
                    lambda limit, meter: fetch_listings(point, transport, limit=limit, meter=meter), budget=settings)
    if result[0] is not None:
        return result
    # A failed new-ZIP lookup does not invalidate nearby recently indexed shops.
    # This remains explicitly partial/stale and never spends another provider call.
    with factory() as db:
        rows = db.scalars(select(PublicListing).where(PublicListing.fetched_at >= now() - STALE)
                          .order_by(PublicListing.fetched_at.desc()).limit(MAX_LISTINGS)).all()
        nearby = []
        checked = None
        for row in rows:
            try:
                if distance_miles(point, row.value['point']) <= RADIUS_MILES:
                    nearby.append(row.value)
                    checked = min(checked, utc(row.fetched_at)) if checked else utc(row.fetched_at)
            except (DirectoryUnavailable, KeyError, TypeError, IndexError):
                continue
    return ({'listings': nearby}, 'stale', checked) if nearby else result
