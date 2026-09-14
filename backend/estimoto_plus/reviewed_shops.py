"""Current business/contact verification, independent of artwork availability.

Only exact reviewed public identities enter discovery. No runtime web scraping,
name-based logo guesses, inferred Google scores or customer data are involved.
"""
from datetime import date, timedelta
from functools import lru_cache
import json
import math
import re
from urllib.parse import urlsplit

from . import shop_media_catalog as media
from .models import now

RESULT_LIMIT = 30
REVIEW_DAYS = 90
SPECIALTIES = {'pdr', 'collision', 'maintenance', 'mechanical'}


def public_website(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        # Query parameters may identify a particular official branch. These
        # links are opened by the customer, never fetched by this service.
        return media.official_url(parsed._replace(query='', fragment='').geturl())
    except ValueError:
        return False


def current(entry):
    try:
        checked = date.fromisoformat(entry['checked_at'][:10])
        return now().date() - timedelta(days=REVIEW_DAYS) <= checked <= now().date()
    except (ValueError, TypeError, KeyError):
        return False


def valid_business(entry):
    return (isinstance(entry, dict) and entry.get('business_verified') is True and
            isinstance(entry.get('source_id'), str) and media.SOURCE.fullmatch(entry['source_id']) and
            bool(media.identity(entry.get('name'))) and isinstance(entry.get('address'), str) and
            isinstance(entry.get('source_point'), list) and len(entry['source_point']) == 2 and
            all(isinstance(v, (int, float)) and math.isfinite(v) for v in entry['source_point']) and
            -90 <= entry['source_point'][0] <= 90 and -180 <= entry['source_point'][1] <= 180 and
            bool(media.identity(entry.get('verified_address'))) and
            public_website(entry.get('website')) and public_website(entry.get('verification_url')) and
            isinstance(entry.get('phone'), str) and
            re.fullmatch(r'\+?[0-9 ()\-\.]{7,24}', entry['phone']) is not None and
            7 <= len(re.sub(r'\D', '', entry['phone'])) <= 15 and
            isinstance(entry.get('specialties'), list) and bool(entry['specialties']) and
            all(s in SPECIALTIES for s in entry['specialties']) and
            isinstance(entry.get('description'), str) and 1 <= len(entry['description']) <= 1000 and
            isinstance(entry.get('evidence'), str) and bool(entry['evidence'].strip()))


@lru_cache(maxsize=1)
def catalog():
    try:
        path = media.ASSET_DIR / 'catalog.json'
        if path.stat().st_size > 2 * 1024 * 1024:
            return {}
        data = json.loads(path.read_text())
        if data.get('schema') != 1:
            return {}
        return {e['source_id']: e for e in data.get('businesses', [])[:2000] if valid_business(e)}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def verified_listing(row):
    if not isinstance(row, dict) or row.get('source') != 'openstreetmap':
        return None
    entry = catalog().get(row.get('source_id'))
    if (not entry or not current(entry) or
            media.identity(row.get('name')) != media.identity(entry.get('name')) or
            media.identity(row.get('address')) != media.identity(entry.get('address'))):
        return None
    if row.get('point') != entry.get('source_point'):
        return None  # A moved map pin requires renewed location verification.
    # Keep the source identity/address for favorite deduplication and artwork;
    # show the official formatted address separately in the mini profile.
    return {**row, 'website': entry['website'], 'phone': entry['phone'],
            'description': entry['description'], 'specialties': entry['specialties'],
            'service_details': entry.get('service_details', []), 'phone_kind': entry.get('phone_kind', 'local'),
            'listed_makes': entry.get('listed_makes', row.get('listed_makes', [])),
            'make_evidence_basis': 'official_website' if entry.get('listed_makes') else 'service:vehicle:brand',
            'specialty_evidence': [{'specialty': s, 'basis': 'official_website',
                                   'source_url': entry['verification_url']} for s in entry['specialties']],
            'verification': {'status': 'contact_confirmed', 'checked_at': entry['checked_at'],
                             'source_url': entry['verification_url'], 'address': entry['verified_address'],
                             'scope': 'Business location, repair services, website and phone checked against its official website.'}}


@lru_cache(maxsize=1)
def partner_websites():
    try:
        path = media.ASSET_DIR / 'catalog.json'
        if path.stat().st_size > 2 * 1024 * 1024:
            return {}
        data = json.loads(path.read_text())
        return {e['source_id']: e for e in data.get('partners', [])[:100]
                if isinstance(e, dict) and public_website(e.get('website')) and
                all(isinstance(e.get(k), str) and e[k] for k in ('source_id', 'name', 'address', 'phone', 'checked_at'))}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def enrich_partner(row):
    entry = partner_websites().get(row.get('source_id'))
    if (row.get('source') == 'estimoto' and entry and current(entry) and
            all(media.identity(row.get(k)) == media.identity(entry[k]) for k in ('name', 'address')) and
            re.sub(r'\D', '', row.get('phone') or '') == re.sub(r'\D', '', entry['phone'])):
        return {**row, 'website': entry['website']}
    return row
