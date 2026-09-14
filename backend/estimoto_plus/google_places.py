"""Live Google Places search. Persist only counters, cooldowns and favorite IDs.

No credentials or customer identity enter URLs, responses, or logs. Requests
have a fixed origin, explicit field mask, byte/time limits and an atomic budget.
"""
import json
import re
import time
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from .calendar_scheduling import utc
from .discovery_models import DirectoryCache, PlacesBudget
from .discovery_provider import DirectoryUnavailable, clean, coordinates, distance_miles, public_url, RADIUS_METERS, RADIUS_MILES
from .models import now

ORIGIN = 'https://places.googleapis.com/v1'
FIELDS = 'id,displayName,formattedAddress,location,types,businessStatus,internationalPhoneNumber,websiteUri,attributions'
ATTRIBUTION = {'name': 'Google Maps', 'url': 'https://maps.google.com/', 'license': 'Google Maps Platform terms'}
SERVICES = {'pdr': 'paintless dent repair', 'collision': 'auto body repair',
            'maintenance': 'car maintenance', 'mechanical': 'auto repair'}
PLACE_ID = re.compile(r'[A-Za-z0-9_-]{4,100}')


def reserve_request(factory, settings):
    if not settings.places_enabled or not settings.google_places_api_key:
        raise DirectoryUnavailable('not_configured')
    current = now()
    day = current.date().isoformat()
    with factory() as db:
        cooldown = db.get(DirectoryCache, 'places:cooldown')
        if cooldown and utc(cooldown.next_attempt_at) > current:
            raise DirectoryUnavailable('cooldown')
        if db.get(PlacesBudget, day) is None:
            try:
                with db.begin_nested():
                    db.add(PlacesBudget(day=day, requests=0))
                    db.flush()
            except IntegrityError:
                pass
        limit = max(0, min(1000, settings.places_daily_requests))
        changed = db.execute(update(PlacesBudget).where(PlacesBudget.day == day,
            PlacesBudget.requests < limit).values(requests=PlacesBudget.requests + 1)).rowcount
        if not changed:
            raise DirectoryUnavailable('budget_exhausted')
        db.execute(delete(PlacesBudget).where(PlacesBudget.day < (current - timedelta(days=14)).date().isoformat()))
        db.commit()  # Charge before I/O, including failures and process crashes.


def _cooldown(factory):
    with factory() as db:
        if db.get(DirectoryCache, 'places:cooldown') is None:
            try:
                with db.begin_nested():
                    db.add(DirectoryCache(key='places:cooldown', value={}))
                    db.flush()
            except IntegrityError:
                pass
        db.execute(update(DirectoryCache).where(DirectoryCache.key == 'places:cooldown')
                   .values(next_attempt_at=now() + timedelta(minutes=1)))
        db.commit()


def _call(factory, transport, settings, path, *, body=None, fields=FIELDS):
    reserve_request(factory, settings)
    try:
        started = time.monotonic()
        headers = {'X-Goog-Api-Key': settings.google_places_api_key,
                   'X-Goog-FieldMask': fields, 'Accept-Encoding': 'identity'}
        with httpx.Client(transport=transport, timeout=httpx.Timeout(8, connect=3),
                          follow_redirects=False, trust_env=False) as client:
            with client.stream('POST' if body is not None else 'GET', ORIGIN + path,
                               headers=headers, json=body) as response:
                if response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity':
                    raise DirectoryUnavailable('provider_error')
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=1024):
                    if len(data) + len(chunk) > 1024 * 1024 or time.monotonic() - started > 10:
                        raise DirectoryUnavailable('response_limit')
                    data.extend(chunk)
        result = json.loads(data)
        if not isinstance(result, dict) or 'error' in result:
            raise DirectoryUnavailable('invalid_response')
        return result
    except (httpx.HTTPError, ValueError, TypeError, RecursionError, DirectoryUnavailable):
        _cooldown(factory)
        raise DirectoryUnavailable('provider_unavailable') from None


def normalize_place(place, *, make=''):
    if not isinstance(place, dict) or not isinstance(place.get('id'), str) or not PLACE_ID.fullmatch(place['id']):
        return None
    name = clean((place.get('displayName') or {}).get('text'), 200) if isinstance(place.get('displayName'), dict) else ''
    types = place.get('types', [])
    location = place.get('location', {})
    if not name or not isinstance(types, list) or 'car_repair' not in types or place.get('businessStatus') != 'OPERATIONAL':
        return None
    try:
        point = coordinates({'lat': location.get('latitude'), 'lon': location.get('longitude')})
    except (DirectoryUnavailable, AttributeError):
        return None
    identifier = place['id']
    source_url = 'https://www.google.com/maps/search/?' + urlencode({'api': '1', 'query': name, 'query_place_id': identifier})
    phone = clean(place.get('internationalPhoneNumber'), 50)
    if not re.fullmatch(r'[+0-9 ()-]{7,50}', phone):
        phone = ''
    attributions = [ATTRIBUTION]
    for value in place.get('attributions', []) if isinstance(place.get('attributions'), list) else []:
        if isinstance(value, dict) and clean(value.get('provider'), 200) and public_url(value.get('providerUri')):
            attributions.append({'name': clean(value['provider'], 200), 'url': public_url(value['providerUri'])})
    return {'id': 'google:' + identifier, 'source': 'google_places', 'source_id': identifier,
            'source_url': source_url, 'name': name, 'kind': 'shop', 'point': point,
            'address': clean(place.get('formattedAddress'), 300), 'city': '', 'postal_codes': [],
            'phone': phone, 'email': '', 'website': public_url(place.get('websiteUri')),
            'specialties': ['mechanical'], 'specialty_evidence': [{'specialty': 'mechanical', 'basis': 'google_place_type', 'source_url': source_url}],
            'description': 'Repair shop listed on Google Maps. Confirm services and availability directly.',
            'listed_makes': [], 'vehicle_match': {'status': 'search_relevance' if make else 'not_verified',
                'make': make or None, 'basis': 'google_places_query' if make else None},
            'mobile_service': False, 'mobile_status': 'unknown', 'accepting_requests': False,
            'request_modes': [], 'favorite': False, 'media': None,
            'verification': {'status': 'public_listing'}, 'source_attributions': attributions}


def search_places(factory, transport, settings, postal, point, *, make='', specialty=None, query=''):
    lat, lon = coordinates({'lat': point[0], 'lon': point[1]})
    make = clean(make, 60)
    service = SERVICES.get(specialty, 'auto repair')
    text = ' '.join(v for v in (clean(query, 120), make, service, 'near', postal, 'USA') if v)
    data = _call(factory, transport, settings, '/places:searchText',
        fields=','.join('places.' + f for f in FIELDS.split(',')) + ',nextPageToken',
        body={'textQuery': text, 'includedType': 'car_repair', 'strictTypeFiltering': True,
              'regionCode': 'US', 'languageCode': 'en', 'pageSize': 20,
              'locationBias': {'circle': {'center': {'latitude': lat, 'longitude': lon}, 'radius': RADIUS_METERS}}})
    values = data.get('places', [])
    if not isinstance(values, list) or len(values) > 20:
        raise DirectoryUnavailable('invalid_response')
    listings = {}
    for value in values:
        row = normalize_place(value, make=make)
        if row and distance_miles(point, row['point']) <= RADIUS_MILES:
            listings[row['source_id']] = row
    return {'listings': list(listings.values()), 'more_available': bool(data.get('nextPageToken'))}


def validate_place(factory, transport, settings, identifier):
    if not PLACE_ID.fullmatch(identifier):
        return None
    row = normalize_place(_call(factory, transport, settings, '/places/' + identifier))
    return row if row and row['source_id'] == identifier else None


def places_zip(factory, transport, settings, postal):
    """Fallback when the public ZIP service fails; never cache Google geodata."""
    data = _call(factory, transport, settings, '/places:searchText',
        fields='places.location,places.types,places.addressComponents',
        body={'textQuery': postal + ', USA', 'regionCode': 'US', 'pageSize': 1})
    values = data.get('places', [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise DirectoryUnavailable('zip_unavailable')
    value = values[0]
    components = value.get('addressComponents', [])
    if not isinstance(components, list) or not isinstance(value.get('location'), dict):
        raise DirectoryUnavailable('zip_unavailable')
    def has(kind, text):
        return any(isinstance(c, dict) and isinstance(c.get('types'), list) and kind in c['types'] and c.get('shortText') == text for c in components)
    if not isinstance(value.get('types'), list) or 'postal_code' not in value['types'] or not has('postal_code', postal) or not has('country', 'US'):
        raise DirectoryUnavailable('zip_unavailable')
    return {'postal_code': postal, 'point': coordinates({'lat': value['location'].get('latitude'), 'lon': value['location'].get('longitude')})}
