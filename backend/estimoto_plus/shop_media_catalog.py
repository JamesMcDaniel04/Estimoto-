"""Reviewed business artwork, served locally without an open image proxy.

The catalog binds each independent shop to its public listing identity. Brand
aliases are explicit exact names, never a search term or substring match.
"""
from functools import lru_cache
import hashlib
from io import BytesIO
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from PIL import Image
from sqlalchemy.orm import Session

from .auth import db_session
from .calendar_scheduling import utc
from .discovery_cache import STALE
from .discovery_models import PublicListing
from .models import now

ASSET_DIR = Path(__file__).parent / 'shop_media'
ORIGIN = 'https://estimoto-plus-api.fly.dev'
SOURCE = re.compile(r'(node|way|relation):([1-9][0-9]{0,18})\Z')
DIGEST = re.compile(r'[a-f0-9]{64}\Z')
MAX_BYTES = 512 * 1024
router = APIRouter(tags=['public shop artwork'])


def identity(value):
    return ' '.join(value.casefold().split()) if isinstance(value, str) else ''


def official_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(c) < 33 for c in value):
        return False
    try:
        u = urlsplit(value)
        if (u.scheme != 'https' or not u.hostname or u.username or u.password or
                u.port not in (None, 443) or u.query or u.fragment or
                '.' not in u.hostname or u.hostname.endswith(('.local', '.localhost', '.internal'))):
            return False
        try:
            return ipaddress.ip_address(u.hostname).is_global
        except ValueError:
            return True
    except ValueError:
        return False


@lru_cache(maxsize=256)
def artwork(digest):
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        return None
    try:
        path = ASSET_DIR / (digest + '.png')
        if path.is_symlink() or not 32 <= path.stat().st_size <= MAX_BYTES:
            return None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            return None
        with Image.open(BytesIO(data)) as image:
            if image.format != 'PNG' or not (1 <= image.width <= 512 and 1 <= image.height <= 512):
                return None
            image.verify()
        return data
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def valid_entry(entry):
    if not isinstance(entry, dict) or entry.get('kind') not in ('logo', 'photo'):
        return False
    credit = entry.get('attribution')
    return (official_url(entry.get('source_url')) and isinstance(credit, str) and
            1 <= len(credit) <= 1000 and not any(ord(c) < 32 for c in credit) and
            isinstance(entry.get('evidence'), str) and bool(entry['evidence'].strip()) and
            artwork(entry.get('sha256')) is not None)


@lru_cache(maxsize=1)
def catalog():
    try:
        path = ASSET_DIR / 'catalog.json'
        if path.stat().st_size > 2 * 1024 * 1024:
            return {}, {}
        data = json.loads(path.read_text())
        if data.get('schema') != 1:
            return {}, {}
        shops, brands = {}, {}
        for entry in data.get('shops', [])[:2000]:
            if (valid_entry(entry) and isinstance(entry.get('source_id'), str) and
                    SOURCE.fullmatch(entry['source_id']) and identity(entry.get('name'))):
                shops[entry['source_id']] = entry
        for entry in data.get('brands', [])[:100]:
            if valid_entry(entry) and entry['kind'] == 'logo':
                for name in entry.get('names', [])[:20]:
                    if identity(name):
                        brands[identity(name)] = entry
        return shops, brands
    except (OSError, ValueError, TypeError, AttributeError):
        return {}, {}


def listing_artwork(row):
    if not isinstance(row, dict) or row.get('source') != 'openstreetmap':
        return None
    source_id = row.get('source_id')
    if not isinstance(source_id, str) or not SOURCE.fullmatch(source_id):
        return None
    shops, brands = catalog()
    if source_id in shops:
        entry = shops[source_id]
        # A renamed or relocated listing must not inherit an old business logo.
        if (identity(row.get('name')) != identity(entry.get('name')) or
                identity(row.get('address')) != identity(entry.get('address'))):
            return None
        return entry
    entry = brands.get(identity(row.get('name')))
    if entry:
        # Chain naming alone does not prove the identity of a branch. Reuse a
        # mark only when OSM also points to its reviewed official website.
        try:
            host = (urlsplit(row.get('website') or '').hostname or '').removeprefix('www.')
            approved = (urlsplit(entry['source_url']).hostname or '').removeprefix('www.')
            if host and host == approved:
                return entry
        except ValueError:
            pass
    return None


def listing_media(row):
    entry = listing_artwork(row)
    if entry is None:
        return None
    kind, number = row['source_id'].split(':')
    return {'url': f"{ORIGIN}/public/shop-media/{kind}/{number}/{entry['sha256']}.png",
            'kind': entry['kind'], 'attribution': entry['attribution'],
            'source_url': entry['source_url'],
            'background': 'dark' if entry.get('background') == 'dark' else 'light'}


@router.get('/public/shop-media/{source_kind}/{source_number}/{filename}')
def public_artwork(source_kind: str, source_number: str, filename: str,
                   db: Session = Depends(db_session)):
    from .reviewed_shops import verified_listing

    source_id = source_kind + ':' + source_number
    if not SOURCE.fullmatch(source_id) or not filename.endswith('.png'):
        raise HTTPException(404, 'Shop image unavailable.')
    digest = filename[:-4]
    if not DIGEST.fullmatch(digest):
        raise HTTPException(404, 'Shop image unavailable.')
    row = db.get(PublicListing, source_id)
    # A known content hash is not sufficient after the listing moves, its
    # business review expires, or its public directory record becomes stale.
    if (row is None or row.fetched_at is None or utc(row.fetched_at) < now() - STALE or
            verified_listing(row.value) is None):
        raise HTTPException(404, 'Shop image unavailable.')
    entry = listing_artwork(row.value)
    if entry is None or entry['sha256'] != digest:
        raise HTTPException(404, 'Shop image unavailable.')
    data = artwork(digest)
    if data is None:
        raise HTTPException(404, 'Shop image unavailable.')
    return Response(data, media_type='image/png', headers={
        'Cache-Control': 'public, max-age=86400',
        'ETag': '"' + digest + '"',
        'Access-Control-Allow-Origin': '*',
        'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff',
    })
