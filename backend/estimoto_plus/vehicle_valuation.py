"""Customer-initiated CarsXE values with private history kept off the provider.

No raw CarsXE response, query URL, key, or VIN is persisted in this cache or
returned to the client. One row per vehicle bounds storage; paid attempts use
committed leases and a shared daily budget before any network I/O.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import http.client
import json
import re
import time
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .auth import current_customer, db_session
from .calendar_scheduling import lock_customer, utc
from .customer_routes import consume_rate, owned
from .graph_models import KnowledgeReceipt, KnowledgeRecord
from .models import Customer, Vehicle, now, uid
from .valuation_models import VehicleValuationCache, VehicleValuationHistory, ValuationProviderState
from .vehicle_images import _fetch_https

router = APIRouter(prefix='/v1/vehicles')
CONDITIONS = {'excellent': 'xclean', 'clean': 'clean', 'average': 'avg', 'rough': 'rough'}
STATES = set('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split())
GROUPS = {'oil_change': 'maintenance', 'tires': 'maintenance', 'brakes': 'maintenance',
          'battery': 'maintenance', 'maintenance': 'maintenance', 'repair': 'repair',
          'diagnostics': 'repair', 'collision': 'repair', 'pdr': 'repair', 'modification': 'modification'}
UNAVAILABLE = 'Vehicle values are unavailable right now. Your saved history is still available.'
MAX_CACHE_ROWS = 10000


class ValuationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    state: str
    condition: Literal['excellent', 'clean', 'average', 'rough']

    @field_validator('state')
    @classmethod
    def us_state(cls, value):
        if value not in STATES:
            raise ValueError('Choose a US state abbreviation.')
        return value


@dataclass
class ProviderResult:
    payload: dict | None = None
    retry_seconds: int = 300
    global_backoff: int = 0


def money(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Invalid provider amount')
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or abs(amount) > 10_000_000:
            raise ValueError('Invalid provider amount')
        return int((amount * 100).quantize(Decimal('1')))
    except (InvalidOperation, OverflowError):
        raise ValueError('Invalid provider amount') from None


def safe_text(value, maximum=100):
    return value.strip() if (isinstance(value, str) and 0 < len(value.strip()) <= maximum and
                            not any(ord(c) < 32 for c in value)) else None


def normalize(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower())


def parse_provider(data, snapshot):
    if not isinstance(data, dict) or data.get('success') is False or data.get('country', 'US') != 'US':
        raise ValueError('Invalid provider result')
    echoed = data.get('input')
    if isinstance(echoed, dict):
        for field in ('vin', 'mileage', 'state', 'condition'):
            if field in echoed and str(echoed[field]) != str(snapshot[field]):
                raise ValueError('Provider input mismatch')
    for provider_field, field in (('model_year', 'year'), ('make', 'make'), ('model', 'model')):
        if data.get(provider_field) is not None and normalize(data[provider_field]) != normalize(snapshot[field]):
            raise ValueError('Provider vehicle mismatch')
    vin_matches = isinstance(echoed, dict) and echoed.get("vin") == snapshot["vin"]
    identity_fields = (("model_year", "year"), ("make", "make"), ("model", "model"))
    ymm_matches = all(data.get(p) is not None and normalize(data[p]) == normalize(snapshot[k])
                      for p, k in identity_fields)
    if not (vin_matches or ymm_matches):
        raise ValueError("Provider identity evidence missing")
    buckets = []
    for prefix, kind in (('retail', 'retail'), ('whole', 'wholesale')):
        key = prefix + '_' + CONDITIONS[snapshot['condition']]
        raw = data.get(key)
        if not isinstance(raw, dict):
            continue
        try:
            base, mileage, equipment, regional = [money(raw.get(part + '_' + key))
                                                  for part in ('base', 'mileage', 'add_deduct', 'regional')]
            adjusted_key = "adjusted_" + key
            total = money(raw[adjusted_key]) if adjusted_key in raw else base + mileage + equipment + regional
            if base < 0 or not 0 < total <= 1_000_000_000:
                continue
        except ValueError:
            continue
        buckets.append({'kind': kind, 'condition': snapshot['condition'], 'amount_cents': total,
                        'amount_basis': 'provider_adjusted' if adjusted_key in raw else 'provider_components',
                        'base_cents': base, 'mileage_adjustment_cents': mileage,
                        'equipment_adjustment_cents': equipment, 'regional_adjustment_cents': regional})
    if not buckets:
        raise ValueError('No complete provider buckets')
    return {'buckets': buckets, 'provider_publish_date': safe_text(data.get('publish_date'), 40),
            'provider_region': safe_text(data.get('state'), 20)}


def fetch_valuation(settings, snapshot):
    # This stdlib transport avoids httpx's URL-bearing INFO logs. Only a fixed
    # endpoint is used, redirects are refused, DNS/TLS and bytes are bounded.
    params = {k: snapshot[k] for k in ('vin', 'mileage', 'state', 'condition')}
    params['key'] = settings.carsxe_api_key
    try:
        status, raw = _fetch_https('https://api.carsxe.com/v2/marketvalue?' + urlencode(params),
                                  max_bytes=64 * 1024, deadline=time.monotonic() + 25)
        if status in {400, 404}:
            return ProviderResult(retry_seconds=86400)
        if status in {401, 402, 403, 429}:
            return ProviderResult(retry_seconds=3600, global_backoff=3600)
        if status != 200:
            return ProviderResult(global_backoff=300)
        payload = parse_provider(json.loads(raw), snapshot)
        return ProviderResult(payload, retry_seconds=86400)
    except (ValueError, OSError, TimeoutError, RecursionError, http.client.HTTPException):
        # Never surface provider exceptions, which may contain query secrets.
        return ProviderResult(global_backoff=300)


def history_summary(db, customer_id, vehicle_id):
    counts = db.execute(select(KnowledgeRecord.service_type, func.count(),
                               func.coalesce(func.sum(KnowledgeRecord.cost_cents), 0),
                               func.count(KnowledgeRecord.cost_cents)).where(
        KnowledgeRecord.customer_id == customer_id, KnowledgeRecord.vehicle_id == vehicle_id)
        .group_by(KnowledgeRecord.service_type)).all()
    categories = {key: {'kind': key, 'records_count': 0, 'costs_cents': 0}
                  for key in ('maintenance', 'repair', 'modification', 'other')}
    with_cost = 0
    for service, count, cost, cost_count in counts:
        row = categories[GROUPS.get(service, 'other')]
        row['records_count'] += count
        row['costs_cents'] += int(cost)
        with_cost += cost_count
    receipt_count, records_receipts = db.execute(select(func.count(KnowledgeReceipt.id),
        func.count(func.distinct(KnowledgeReceipt.record_id))).join(KnowledgeRecord,
            KnowledgeRecord.id == KnowledgeReceipt.record_id).where(
        KnowledgeRecord.customer_id == customer_id, KnowledgeRecord.vehicle_id == vehicle_id,
        KnowledgeReceipt.customer_id == customer_id, KnowledgeReceipt.status == 'saved')).one()
    total = sum(row['records_count'] for row in categories.values())
    factors = []
    if total:
        factors.append(f'{total} customer-reported service records; {with_cost} include a recorded cost.')
    if categories['maintenance']['records_count']:
        factors.append(f"{categories['maintenance']['records_count']} maintenance records document reported care.")
    if categories['repair']['records_count']:
        factors.append(f"{categories['repair']['records_count']} repair records are part of the disclosed history.")
    if categories['modification']['records_count']:
        factors.append('Modifications are recorded separately; their effect on resale value is not assessed.')
    if receipt_count:
        factors.append(f'{records_receipts} records have attached receipts; receipt contents and workmanship are not verified.')
    if not total:
        factors.append('No service history has been recorded for this vehicle yet.')
    factors.append('Recorded spending is not added to the market value estimate.')
    return {'records_count': total, 'costs_cents': sum(row['costs_cents'] for row in categories.values()),
            'records_with_cost': with_cost, 'records_with_receipts': records_receipts,
            'receipt_count': receipt_count, 'categories': [row for row in categories.values()
                if row['kind'] != 'other' or row['records_count']], 'factors': factors}


def response(snapshot, history, *, status='unavailable', cached=False, payload=None,
             fetched_at=None, expires_at=None, retry=None):
    return {'vehicle_id': snapshot['vehicle_id'], 'status': status, 'provider': 'CarsXE',
            'currency': 'USD', 'condition': snapshot['condition'], 'state': snapshot['state'],
            'mileage': snapshot['mileage'], 'cached': cached, 'fetched_at': utc(fetched_at).isoformat() if fetched_at else None,
            'expires_at': utc(expires_at).isoformat() if expires_at else None,
            'provider_publish_date': (payload or {}).get('provider_publish_date'),
            'provider_region': (payload or {}).get('provider_region'),
            'buckets': (payload or {}).get('buckets', []), 'history': history,
            'message': ('CarsXE retail and wholesale estimates include provider adjustments. They are not a purchase offer or a private-sale quote.'
                        if status == 'available' else 'A valuation lookup is already in progress. Try again shortly.'
                        if status == 'pending' else UNAVAILABLE), 'retry_after_seconds': retry}


HISTORY_ROWS_PER_VEHICLE = 50


def record_history(db, customer_id, vehicle_id, snapshot, digest, payload):
    # Prune before adding and without flushing, so the caller's commit still
    # carries the cache row that lost-acknowledgment recovery keys on.
    with db.no_autoflush:
        stale = db.scalars(select(VehicleValuationHistory.id)
                           .where(VehicleValuationHistory.vehicle_id == vehicle_id)
                           .order_by(VehicleValuationHistory.created_at.desc(), VehicleValuationHistory.id.desc())
                           .offset(HISTORY_ROWS_PER_VEHICLE - 1)).all()
    if stale:
        db.execute(delete(VehicleValuationHistory).where(VehicleValuationHistory.id.in_(stale)))
    db.add(VehicleValuationHistory(customer_id=customer_id, vehicle_id=vehicle_id, state=snapshot['state'],
                                   condition=snapshot['condition'], mileage=snapshot['mileage'],
                                   input_hash=digest, payload=payload))


def history_view(row):
    return {'id': row.id, 'state': row.state, 'condition': row.condition, 'mileage': row.mileage,
            'created_at': utc(row.created_at).isoformat(), 'payload': row.payload}


def provider_lock(db):
    if db.get_bind().dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.execute(insert(ValuationProviderState).values(id=1, day_bucket=0, count=0)
               .on_conflict_do_nothing(index_elements=['id']))
    db.execute(update(ValuationProviderState).where(ValuationProviderState.id == 1).values(id=1))
    db.expire_all()
    return db.get(ValuationProviderState, 1)


@router.post('/{vehicle_id}/valuation')
def valuation(vehicle_id: str, body: ValuationInput, request: Request,
              c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    customer_id = c.id
    lock_customer(db, customer_id)
    v = owned(db, Vehicle, vehicle_id, c)
    if not re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}', v.vin or '') or not 0 <= v.mileage <= 5_000_000:
        raise HTTPException(422, 'Save a valid 17-character VIN and current mileage before checking vehicle value.')
    snapshot = {k: getattr(v, k) for k in ('vin', 'mileage', 'year', 'make', 'model')}
    snapshot.update(vehicle_id=vehicle_id, state=body.state, condition=body.condition)
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    history = history_summary(db, customer_id, vehicle_id)
    settings = request.app.state.settings
    stamp = now()
    entry = db.get(VehicleValuationCache, vehicle_id)
    if entry and entry.customer_id != customer_id:
        raise HTTPException(404, 'Not found.')
    if entry and entry.lease_until and utc(entry.lease_until) > stamp:
        return response(snapshot, history, status='pending', retry=60)
    if entry and entry.input_hash == digest and utc(entry.retry_at) > stamp:
        if entry.payload:
            record_history(db, customer_id, vehicle_id, snapshot, digest, entry.payload)
            db.commit()
        return response(snapshot, history, status='available' if entry.payload else 'unavailable',
                        cached=True, payload=entry.payload, fetched_at=entry.fetched_at,
                        expires_at=entry.retry_at, retry=None if entry.payload else max(1, int((utc(entry.retry_at)-stamp).total_seconds())))
    if not settings.valuation_enabled or not settings.carsxe_api_key or c.demo:
        return response(snapshot, history)
    state = provider_lock(db)
    daily_limit = max(0, min(settings.valuation_daily_requests, 200))
    day = int(stamp.timestamp() // 86400)
    if state.day_bucket != day:
        state.day_bucket, state.count = day, 0
    if (state.blocked_until and utc(state.blocked_until) > stamp) or state.count >= daily_limit:
        return response(snapshot, history, retry=3600)
    if not entry and db.scalar(select(func.count()).select_from(VehicleValuationCache)) >= MAX_CACHE_ROWS:
        return response(snapshot, history, retry=3600)
    consume_rate(db, customer_id, 'vehicle_valuation', 4)
    state.count += 1
    token = uid()
    if not entry:
        entry = VehicleValuationCache(vehicle_id=vehicle_id, customer_id=customer_id, input_hash=digest, retry_at=stamp)
        db.add(entry)
    entry.input_hash, entry.payload, entry.fetched_at = digest, None, None
    entry.retry_at, entry.lease_until, entry.lease_token = stamp, stamp + timedelta(seconds=60), token
    db.commit()  # A failed/uncertain reservation never starts paid I/O.
    result = fetch_valuation(settings, snapshot)
    # lock_customer expires the identity map before re-reading the lease and
    # vehicle; objects retained across provider I/O must never be trusted.
    lock_customer(db, customer_id)
    current = db.get(Vehicle, vehicle_id)
    entry = db.get(VehicleValuationCache, vehicle_id)
    if not current or current.customer_id != customer_id:
        raise HTTPException(404, 'Not found.')
    if not entry or entry.input_hash != digest or entry.lease_token != token:
        return response(snapshot, history, status='pending', retry=60)
    stamp = now()
    entry.payload, entry.fetched_at = result.payload, stamp
    entry.retry_at = stamp + timedelta(seconds=result.retry_seconds)
    entry.lease_token = entry.lease_until = None
    if result.global_backoff:
        state = provider_lock(db)
        state.blocked_until = stamp + timedelta(seconds=result.global_backoff)
    if result.payload:
        record_history(db, customer_id, vehicle_id, snapshot, digest, result.payload)
    db.commit()
    # The lookup is tied to the exact saved vehicle version at click time.
    if any(getattr(current, k) != snapshot[k] for k in ('vin', 'mileage', 'year', 'make', 'model')):
        raise HTTPException(422, 'Vehicle details changed during the lookup. Check the saved vehicle and try again.')
    return response(snapshot, history_summary(db, customer_id, vehicle_id),
                    status='available' if result.payload else 'unavailable', payload=result.payload,
                    fetched_at=stamp, expires_at=entry.retry_at, retry=None if result.payload else result.retry_seconds)


@router.get('/{vehicle_id}/valuations')
def list_valuations(vehicle_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned(db, Vehicle, vehicle_id, c)
    rows = db.scalars(select(VehicleValuationHistory)
                      .where(VehicleValuationHistory.customer_id == c.id, VehicleValuationHistory.vehicle_id == vehicle_id)
                      .order_by(VehicleValuationHistory.created_at.desc(), VehicleValuationHistory.id.desc())).all()
    return {'vehicle_id': vehicle_id, 'valuations': [history_view(r) for r in rows]}


@router.delete('/{vehicle_id}/valuations/{valuation_id}', status_code=204)
def delete_valuation(vehicle_id: str, valuation_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned(db, Vehicle, vehicle_id, c)
    row = db.get(VehicleValuationHistory, valuation_id)
    if row is None or row.customer_id != c.id or row.vehicle_id != vehicle_id:
        raise HTTPException(404, 'Not found.')
    db.delete(row)
    db.commit()
