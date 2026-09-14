"""Customer-owned directory search, dedicated shops and explicit visit admission."""
import hashlib
import re
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import current_customer, db_session
from .calendar_scheduling import consume_rate as _consume_rate, lock_customer, utc
from .discovery_cache import public_directory, zip_location
from .discovery_models import DedicatedShop, PublicListing
from .discovery_provider import ATTRIBUTIONS, DirectoryUnavailable, RADIUS_MILES, distance_miles
from .models import Customer, Provider, Vehicle, now
from .postal import canonical_zip
from .shop_models import MyShop

Specialty = Literal['pdr', 'collision', 'maintenance', 'mechanical']
router = APIRouter(prefix='/v1/discovery', tags=['customer discovery'])


def owned_vehicle(db, vehicle_id, customer_id):
    row = db.get(Vehicle, vehicle_id) if vehicle_id else None
    if vehicle_id and (not row or row.customer_id != customer_id):
        raise HTTPException(404, 'Vehicle not found.')
    return row


def address_zip(provider):
    match = re.search(r'(?<!\d)([0-9]{5})(?:-[0-9]{4})?(?:\s*,?\s*(?:USA|US|United States))?\s*$', provider.address or '', re.IGNORECASE)
    return match[1] if match else None


def address_hash(provider):
    return hashlib.sha256(provider.address.encode()).hexdigest()


def valid_admission(provider, postal, mode, proof):
    if mode is None:
        return postal in provider.postal_codes
    if mode == 'mobile':
        return provider.mobile_service and postal in provider.postal_codes
    if mode != 'shop_visit' or provider.kind != 'shop' or not isinstance(proof, dict):
        return False
    try:
        return (proof['postal_code'] == postal and proof['address_hash'] == address_hash(provider) and
                proof['shop_postal_code'] == address_zip(provider) and proof['distance_basis'] == 'zip_centroid' and
                distance_miles(proof['customer_point'], proof['shop_point']) <= RADIUS_MILES)
    except (KeyError, TypeError, ValueError, IndexError, DirectoryUnavailable):
        return False


def admission(request, provider, postal, mode):
    if mode is None:
        return {} if postal in provider.postal_codes else None
    if mode == 'mobile':
        return {} if provider.mobile_service and postal in provider.postal_codes else None
    location = address_zip(provider)
    if provider.kind != 'shop' or not location:
        return None
    if not request.app.state.settings.discovery_enabled:
        raise HTTPException(503, 'Nearby shop visits are unavailable. Please try later.')
    factory, transport = request.app.state.session_factory, request.app.state.discovery_transport
    origin, origin_state, _ = zip_location(factory, transport, postal)
    destination, dest_state, checked = zip_location(factory, transport, location)
    if origin_state != 'ready' or dest_state != 'ready':
        raise HTTPException(503, 'The shop distance could not be verified. Please try later.')
    miles = distance_miles(origin['point'], destination['point'])
    if miles > RADIUS_MILES:
        return None
    return {'postal_code': postal, 'shop_postal_code': location, 'address_hash': address_hash(provider),
            'customer_point': origin['point'], 'shop_point': destination['point'], 'distance_miles': miles,
            'distance_basis': 'zip_centroid', 'checked_at': checked.isoformat()}


def _public_provider(p):
    data = {k: getattr(p, k) for k in ('id', 'name', 'kind', 'specialties', 'postal_codes', 'city', 'address',
                                      'phone', 'mobile_service', 'accepting_requests', 'description')}
    return {**data, 'source': 'estimoto', 'source_id': p.source_id, 'source_url': '', 'website': '', 'email': '',
            'mobile_status': 'listed' if p.mobile_service else 'not_listed',
            'specialty_evidence': [{'specialty': s, 'basis': 'owner_declared', 'source_url': ''} for s in p.specialties],
            'vehicle_match': {'status': 'not_verified', 'make': None, 'basis': None}, 'favorite': False,
            'request_modes': [], 'listed_makes': []}


def search(db, request, customer, postal, vehicle=None, specialty=None, mobile_only=False):
    empty = {'postal_code': postal, 'radius_miles': 30, 'distance_basis': 'zip_centroid', 'status': 'unavailable',
             'exhaustive': False, 'truncated': False, 'checked_at': None, 'source_attributions': ATTRIBUTIONS,
             'providers': [], 'shop_visit_alternatives': [], 'message': 'Nearby listings are unavailable. Try again later.'}
    if customer.demo or not request.app.state.settings.discovery_enabled:
        return empty
    factory, transport = request.app.state.session_factory, request.app.state.discovery_transport
    center, geo_state, geo_checked = zip_location(factory, transport, postal)
    if center is None:
        return empty
    public, public_state, checked = public_directory(factory, transport, postal, center['point'], request.app.state.settings)
    candidates = []
    status = 'ready' if geo_state == public_state == 'ready' else 'stale' if public is not None else 'unavailable'
    favorites = db.scalars(select(DedicatedShop).where(DedicatedShop.customer_id == customer.id,
                          DedicatedShop.vehicle_id == vehicle.id)).all() if vehicle else []
    favorite_refs = {(f.source, f.source_id) for f in favorites if not specialty or f.specialty == specialty}
    partners = db.scalars(select(Provider).where(Provider.public_visible.is_(True), Provider.demo_only.is_(False)).order_by(Provider.id).limit(501)).all()
    partner_limit = len(partners) > 500
    unknown_locations, cold_lookups, places = 0, 0, {postal: (center, geo_state, geo_checked)}
    for p in partners[:500]:
        location = address_zip(p)
        if not location:
            unknown_locations += 1
            continue  # Service ZIP coverage is not a physical business location.
        if location not in places:
            cached_place = zip_location(factory, transport, location, allow_fetch=False)
            if cached_place[1] != 'ready' and cold_lookups < 4:
                cold_lookups += 1
                cached_place = zip_location(factory, transport, location)
            places[location] = cached_place
        place, place_state, _ = places[location]
        if place is None:
            unknown_locations += 1
            continue
        miles = distance_miles(center['point'], place['point'])
        if miles > RADIUS_MILES:
            continue
        if place_state == 'stale' and status == 'ready':
            status = 'stale'
        row = _public_provider(p)
        row['distance_miles'] = round(miles, 1)
        if p.accepting_requests and (not specialty or specialty in p.specialties):
            if p.kind == 'shop':
                row['request_modes'].append('shop_visit')
            if p.mobile_service and postal in p.postal_codes:
                row['request_modes'].append('mobile')
        candidates.append(row)
    for public_row in (public or {}).get('listings', []):
        row = dict(public_row)
        row['distance_miles'] = round(distance_miles(center['point'], row['point']), 1)
        candidates.append(row)
    for row in candidates:
        row['favorite'] = (row['source'], row['source_id']) in favorite_refs
        row['favorite_references'] = [favorite_view(f) for f in favorites
                                     if (f.source, f.source_id) == (row['source'], row['source_id'])]
        makes = row.pop('listed_makes', [])
        if vehicle and vehicle.make.casefold().strip() in {m.casefold() for m in makes}:
            row['vehicle_match'] = {'status': 'listed_make', 'make': vehicle.make, 'basis': 'service:vehicle:brand'}
        row.pop('point', None)
    def rank(row):
        matching = not specialty or specialty in row['specialties']
        return (not row['favorite'], not matching, row['source'] != 'estimoto' if matching else True,
                row['vehicle_match']['status'] != 'listed_make', row['distance_miles'], row['name'].casefold(), row['id'])
    candidates.sort(key=rank)
    seen, unique = {}, []
    for row in candidates:
        # A shared chain phone is not a physical-shop identity. Only merge
        # sources that publish the same complete street address and ZIP.
        name = re.sub(r'\W+', '', row['name'].casefold())
        address = row['address'].strip()
        complete_address = (re.match(r'^\d{1,8}[A-Za-z]?\s+[A-Za-z]', address) is not None and
                            re.search(r'(?<!\d)\d{5}(?:-\d{4})?\s*$', address) is not None)
        location = re.sub(r'\W+', '', address.casefold()) if complete_address else ''
        phone = re.sub(r'\D', '', row['phone'])
        key = (name, phone, location) if location else (row['source'], row['source_id'])
        if key in seen:
            position = seen[key]
            previous = unique[position]
            favorite = previous['favorite'] or row['favorite']
            references = {(f['vehicle_id'], f['specialty'], f['source'], f['source_id']): f
                          for f in (*previous['favorite_references'], *row['favorite_references'])}
            # A public duplicate must not hide the authenticated handoff for
            # the exact same business. Keep the original source on its fields.
            if row['source'] == 'estimoto' and (not specialty or specialty in row['specialties']):
                unique[position] = row
            unique[position]['favorite'] = favorite
            unique[position]['favorite_references'] = [references[key] for key in sorted(references)]
            continue
        seen[key] = len(unique)
        unique.append(row)
    unique.sort(key=rank)
    if mobile_only:
        primary = [r for r in unique if 'mobile' in r['request_modes'] and (not specialty or specialty in r['specialties'])]
        alternatives = [r for r in unique if r['kind'] == 'shop' and r not in primary]
    else:
        primary, alternatives = unique, []
    truncated = partner_limit or len(primary) + len(alternatives) > 100
    primary = primary[:100]
    alternatives = alternatives[:100 - len(primary)]
    message = 'Approximate distance from your ZIP center. Confirm services and availability with the shop.'
    if mobile_only and not primary and alternatives:
        message = 'No mobile provider lists coverage here. These nearby shops require a shop visit.'
    if status == 'stale':
        message += ' Public listings are cached; the live directory is currently unavailable.'
    elif status == 'unavailable':
        message += ' The public directory is unavailable; participating shops may still appear.'
    if unknown_locations:
        message += ' Some participating shops could not be located from their published address.'
    if truncated:
        message += ' Showing the first 100 listings; coverage is not exhaustive.'
    return {**empty, 'status': status, 'checked_at': (checked or geo_checked).isoformat(), 'providers': primary,
            'shop_visit_alternatives': alternatives, 'truncated': truncated, 'message': message}


@router.get('')
def discovery(request: Request, postal_code: str | None = Query(default=None, max_length=30), radius_miles: int = Query(default=30, ge=30, le=30),
              vehicle_id: str | None = None, specialty: Specialty | None = None, mobile_only: bool = False,
              c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    vehicle = owned_vehicle(db, vehicle_id, c.id)
    postal = canonical_zip(postal_code or c.postal_code)
    if not postal:
        raise HTTPException(422, 'Save a valid ZIP code to find nearby shops.')
    lock_customer(db, c.id)
    try:
        _consume_rate(db, c.id, 'directory_search', 120)
    except HTTPException as exc:
        if exc.status_code == 429:
            raise HTTPException(429, 'Too many directory searches. Please try again later.') from None
        raise
    db.commit()
    return search(db, request, c, postal, vehicle, specialty, mobile_only)


class FavoriteWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    vehicle_id: str = Field(min_length=1, max_length=36)
    source: Literal['estimoto', 'openstreetmap', 'my_shop']
    source_id: str = Field(min_length=1, max_length=100)


def favorite_view(row):
    return {key: getattr(row, key) for key in ('vehicle_id', 'specialty', 'source', 'source_id')}


@router.get('/favorites')
def favorites(vehicle_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned_vehicle(db, vehicle_id, c.id)
    return [favorite_view(r) for r in db.scalars(select(DedicatedShop).where(DedicatedShop.customer_id == c.id,
            DedicatedShop.vehicle_id == vehicle_id).order_by(DedicatedShop.specialty)).all()]


@router.put('/favorites/{specialty}')
def set_favorite(specialty: Specialty, body: FavoriteWrite, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    lock_customer(db, c.id)
    owned_vehicle(db, body.vehicle_id, c.id)
    if body.source == 'estimoto':
        source = db.scalar(select(Provider).where(Provider.source_id == body.source_id, Provider.public_visible.is_(True), Provider.demo_only.is_(c.demo)))
    elif body.source == 'my_shop':
        source = db.scalar(select(MyShop).where(MyShop.id == body.source_id, MyShop.customer_id == c.id, MyShop.deleted.is_(False)))
    else:
        source = db.get(PublicListing, body.source_id)
        if source and utc(source.fetched_at) < now() - timedelta(days=7):
            source = None
    if source is None:
        raise HTTPException(422, 'Choose an available listing or one of your saved shops.')
    key = (c.id, body.vehicle_id, specialty)
    row = db.get(DedicatedShop, key)
    if row is None:
        row = DedicatedShop(customer_id=c.id, vehicle_id=body.vehicle_id, specialty=specialty, source=body.source, source_id=body.source_id)
        db.add(row)
    row.source, row.source_id = body.source, body.source_id
    db.commit()
    return favorite_view(row)


@router.delete('/favorites/{specialty}')
def clear_favorite(specialty: Specialty, vehicle_id: str, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    lock_customer(db, c.id)
    owned_vehicle(db, vehicle_id, c.id)
    row = db.get(DedicatedShop, (c.id, vehicle_id, specialty))
    if row:
        db.delete(row)
    db.commit()
    return {'removed': True}
