"""Bounded public-only queries; customer identity never reaches directory providers."""
import json
import ipaddress
import math
import re
import time
from urllib.parse import urlsplit
import httpx

RADIUS_MILES = 30
RADIUS_METERS = 48280.32
ATTRIBUTIONS = [{'name': '© OpenStreetMap contributors', 'url': 'https://www.openstreetmap.org/copyright',
                 'license': 'ODbL-1.0'}, {'name': 'Zippopotam.us', 'url': 'https://www.zippopotam.us/', 'license': 'See source terms'}]


class DirectoryUnavailable(Exception):
    def __init__(self, status=None):
        super().__init__('Public directory is unavailable.')
        self.status = status


def clean(value, limit=300):
    return value.strip()[:limit] if isinstance(value, str) and not any(ord(c) < 32 for c in value) else ''


def public_url(value):
    value = clean(value, 500)
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username and not parsed.password and parsed.port in (None, 80, 443):
            if parsed.hostname == 'localhost' or parsed.hostname.endswith(('.localhost', '.local', '.internal')):
                return ''
            try:
                if not ipaddress.ip_address(parsed.hostname).is_global:
                    return ''
            except ValueError:
                pass
            return value
    except ValueError:
        pass
    return ''


def distance_miles(a, b):
    a = coordinates({'lat': a[0], 'lon': a[1]})
    b = coordinates({'lat': b[0], 'lon': b[1]})
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.7613 * 2 * math.asin(min(1, math.sqrt(max(0, value))))


def coordinates(data):
    try:
        lat, lon = float(data['lat']), float(data['lon'])
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return [lat, lon]
    except (KeyError, TypeError, ValueError):
        pass
    raise DirectoryUnavailable()


def read_public(method, url, transport, *, form=None, limit=3 * 1024 * 1024, meter=None):
    try:
        started = time.monotonic()
        read_timeout = 5 if url.startswith('https://api.zippopotam.us/') else 20
        with httpx.Client(transport=transport, timeout=httpx.Timeout(read_timeout, connect=5), follow_redirects=False, trust_env=False,
                          headers={'Accept-Encoding': 'identity', 'User-Agent': 'EstimotoPlus/1.0 (https://estimoto.io; support@estimoto.io)'}) as client:
            with client.stream(method, url, data=form) as response:
                if response.headers.get('content-encoding', 'identity') != 'identity':
                    raise DirectoryUnavailable(response.status_code)
                data = bytearray()
                # Consume bounded raw bytes, including error responses, for the shared
                # provider budget. Identity encoding prevents decompression bombs.
                for chunk in response.iter_bytes(chunk_size=1024):
                    if meter is not None:
                        meter['body_bytes'] += len(chunk)
                    if len(data) + len(chunk) >= limit or time.monotonic() - started > 25:
                        raise DirectoryUnavailable(response.status_code)
                    data.extend(chunk)
                if response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity':
                    raise DirectoryUnavailable(response.status_code)
        value = json.loads(data)
        if not isinstance(value, dict):
            raise DirectoryUnavailable()
        return value
    except (httpx.HTTPError, ValueError, TypeError, RecursionError):
        raise DirectoryUnavailable() from None


def fetch_zip(postal, transport):
    if not re.fullmatch(r'[0-9]{5}', postal):
        raise DirectoryUnavailable()
    data = read_public('GET', 'https://api.zippopotam.us/us/' + postal, transport, limit=64 * 1024)
    places = data.get('places')
    if data.get('post code') != postal or data.get('country abbreviation') != 'US' or not isinstance(places, list) or not 1 <= len(places) <= 100 or not isinstance(places[0], dict):
        raise DirectoryUnavailable()
    point = coordinates({'lat': places[0].get('latitude'), 'lon': places[0].get('longitude')})
    return {'point': point, 'postal_code': postal}


def normalize_listing(element):
    if not isinstance(element, dict) or element.get('type') not in ('node', 'way', 'relation') or type(element.get('id')) is not int or not 0 < element['id'] < 2 ** 63:
        raise DirectoryUnavailable()
    tags = element.get('tags')
    if not isinstance(tags, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in tags.items()):
        raise DirectoryUnavailable()
    if tags.get('shop') not in ('car_repair', 'tyres'):
        return None
    name = clean(tags.get('name'), 200)
    if not name or tags.get('access') in ('private', 'no') or tags.get('service') in ('private', 'fleet') or tags.get('opening_hours') == 'closed' or any(
            tags.get(key) in ('yes', 'true', '1') for key in ('fleet', 'private', 'disused', 'abandoned', 'demolished', 'closed')) or any(
            key.startswith(('disused:', 'abandoned:', 'demolished:', 'removed:', 'razed:')) for key in tags):
        return None
    try:
        point = coordinates(element if element.get('type') == 'node' else element.get('center'))
    except DirectoryUnavailable:
        return None
    identifier = f"{element['type']}:{element['id']}"
    source_url = f"https://www.openstreetmap.org/{element['type']}/{element['id']}"
    services = []
    evidence = []
    # Broad shop tags establish a general repair listing, not PDR expertise.
    for specialty, keys in {
        'pdr': ('service:vehicle:paintless_dent_repair', 'service:vehicle:pdr'),
        'collision': ('service:vehicle:body_repair', 'service:vehicle:bodywork'),
        'maintenance': ('service:vehicle:oil_change', 'service:vehicle:tyres'),
        'mechanical': ('service:vehicle:car_repair', 'service:vehicle:diagnostics'),
    }.items():
        exact = next((key for key in keys if tags.get(key) == 'yes'), None)
        if exact:
            services.append(specialty)
            evidence.append({'specialty': specialty, 'basis': 'osm_tag', 'source_url': source_url, 'tag': exact})
    if not services:
        services = ['maintenance'] if tags['shop'] == 'tyres' else ['mechanical']
        evidence = [{'specialty': services[0], 'basis': 'osm_tag', 'source_url': source_url, 'tag': 'shop=' + tags['shop']}]
    # OSM brand/operator identifies a chain, not brands of vehicles serviced.
    makes = [clean(v, 60) for v in clean(tags.get('service:vehicle:brand'), 500).split(';') if clean(v, 60)]
    phone = clean(tags.get('contact:phone') or tags.get('phone'), 50)
    if not re.fullmatch(r'[+0-9 ()-]{7,50}', phone):
        phone = ''
    email = clean(tags.get('contact:email') or tags.get('email'), 200)
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email):
        email = ''
    address = ' '.join(clean(tags.get(k), 100) for k in ('addr:housenumber', 'addr:street', 'addr:city', 'addr:state', 'addr:postcode')).strip()
    return {'id': 'osm:' + identifier, 'source': 'openstreetmap', 'source_id': identifier, 'source_url': source_url,
            'name': name, 'kind': 'shop', 'specialties': services, 'specialty_evidence': evidence, 'postal_codes': [],
            'city': clean(tags.get('addr:city'), 120), 'address': address[:300], 'phone': phone, 'email': email,
            'website': public_url(tags.get('contact:website') or tags.get('website')), 'description': 'Public repair-shop listing. Confirm services directly.',
            'mobile_service': False, 'mobile_status': 'unknown', 'accepting_requests': False, 'request_modes': [],
            'point': point, 'listed_makes': makes, 'vehicle_match': {'status': 'not_verified', 'make': None, 'basis': None},
            'favorite': False}


def fetch_listings(point, transport, *, limit=3 * 1024 * 1024, meter=None):
    lat, lon = coordinates({'lat': point[0], 'lon': point[1]})
    query = f'[out:json][timeout:20];nwr(around:{RADIUS_METERS},{lat:.6f},{lon:.6f})["shop"~"^(car_repair|tyres)$"];out center tags;'
    data = read_public('POST', 'https://overpass-api.de/api/interpreter', transport, form={'data': query}, limit=limit, meter=meter)
    elements = data.get('elements')
    if data.get('remark') or not isinstance(elements, list) or len(elements) > 10000:
        raise DirectoryUnavailable()
    result = {}
    for element in elements:
        row = normalize_listing(element)
        if row and distance_miles(point, row['point']) <= RADIUS_MILES:
            result[row['source_id']] = row
    return {'listings': list(result.values())}
