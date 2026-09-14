import hashlib
from io import BytesIO
import json

from PIL import Image
import pytest

from estimoto_plus import shop_media_catalog as media
from test_api import h
from test_discovery import clients, setup


@pytest.fixture
def artwork(tmp_path, monkeypatch):
    out = BytesIO()
    Image.new('RGB', (120, 60), '#0b4174').save(out, 'PNG')
    data = out.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    (tmp_path / (digest + '.png')).write_bytes(data)
    entry = {'source_id': 'node:1', 'name': 'General repair', 'address': '',
             'sha256': digest, 'kind': 'logo', 'source_url': 'https://shop.example/',
             'attribution': 'General repair · Official website',
             'evidence': 'Exact reviewed public listing and official business website.'}
    def write(shops=None, brands=None):
        (tmp_path / 'catalog.json').write_text(json.dumps({
            'schema': 1, 'shops': [entry] if shops is None else shops,
            'brands': [] if brands is None else brands}))
        media.catalog.cache_clear()
        media.artwork.cache_clear()
    monkeypatch.setattr(media, 'ASSET_DIR', tmp_path)
    write()
    yield entry, data, write
    media.catalog.cache_clear()
    media.artwork.cache_clear()


def test_cached_directory_gains_exact_logo_without_refetch_or_customer_session(artwork, clients):
    entry, data, write = artwork
    client, _ = clients
    _, stub = setup(client)
    # First cache the listing without a logo, as existing customers have it.
    write(shops=[])
    initial = client.get('/v1/discovery', headers=h('alice')).json()
    assert initial['providers'][0]['media'] is None
    calls = len(stub.calls)
    write()
    result = client.get('/v1/discovery', headers=h('alice')).json()
    logo = next(row['media'] for row in result['providers'] if row['source_id'] == 'node:1')
    assert logo['attribution'] == entry['attribution']
    assert logo['source_url'] == entry['source_url']
    assert logo['url'] == f"{media.ORIGIN}/public/shop-media/node/1/{entry['sha256']}.png"
    # An ordinary anonymous image GET returns only reviewed public PNG bytes.
    response = client.get(logo['url'])
    assert response.status_code == 200 and response.content == data
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['cache-control'] == 'public, max-age=86400'
    assert response.headers['access-control-allow-origin'] == '*'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert len(stub.calls) == calls
    assert client.get('/v1/discovery').status_code == 401


@pytest.mark.parametrize('change', [
    {'name': 'Different business'}, {'address': '999 Moved Street'},
    {'source_id': 'node:2'}, {'source': 'estimoto'},
])
def test_artwork_is_not_reused_for_a_different_business(artwork, change):
    row = {'source': 'openstreetmap', 'source_id': 'node:1', 'name': 'General repair', 'address': ''}
    assert media.listing_media(row)
    assert media.listing_media({**row, **change}) is None


def test_exact_reviewed_chain_alias_never_uses_substring_matching(artwork):
    entry, _, write = artwork
    write(shops=[], brands=[{**entry, 'names': ['Example Tire Center']}])
    row = {'source': 'openstreetmap', 'source_id': 'way:21', 'name': 'EXAMPLE TIRE CENTER',
           'website': 'https://www.shop.example/branches/21'}
    assert media.listing_media(row)['url'].startswith(media.ORIGIN + '/public/shop-media/way/21/')
    assert media.listing_media({**row, 'name': 'Not Example Tire Center'}) is None
    assert media.listing_media({**row, 'name': 'Example Tire Center Independent'}) is None
    assert media.listing_media({**row, 'website': 'https://shop.example.evil.test/'}) is None
    assert media.listing_media({**row, 'website': ''}) is None


@pytest.mark.parametrize('bad', [
    {'sha256': '../private'}, {'source_url': 'https://127.0.0.1/admin'},
    {'source_url': 'https://169.254.169.254/'}, {'source_url': 'https://user:secret@shop.example/'},
    {'source_url': 'https://shop.internal/'}, {'source_url': 'javascript:alert(1)'},
    {'source_url': 'https://shop.example/?token=secret'}, {'attribution': 'Untrusted\ncredit'},
    {'kind': 'html'}, {'evidence': ''},
])
def test_invalid_catalog_entries_fail_closed(artwork, bad):
    entry, _, write = artwork
    write(shops=[{**entry, **bad}])
    assert media.catalog() == ({}, {})


def test_tampered_or_missing_asset_does_not_become_a_broken_logo(artwork):
    entry, data, write = artwork
    (media.ASSET_DIR / (entry['sha256'] + '.png')).write_bytes(data + b'tampered')
    write()
    assert media.catalog() == ({}, {})


def test_public_route_cannot_fetch_urls_or_read_other_files(artwork, clients):
    entry, _, _ = artwork
    client, _ = clients
    setup(client)
    client.get('/v1/discovery', headers=h('alice'))
    prefix = '/public/shop-media/'
    for path in (
        'node/1/' + '0' * 64 + '.png',
        'node/999/' + entry['sha256'] + '.png',
        'node/2/' + entry['sha256'] + '.png',
        'customer/1/' + entry['sha256'] + '.png',
        'node/01/' + entry['sha256'] + '.png',
        'node/1/private.pdf', 'node/1/catalog.json',
    ):
        assert client.get(prefix + path).status_code == 404


@pytest.mark.parametrize('change', [
    {'name': 'New unrelated business'}, {'address': '999 New Street'},
    {'point': [39.85, -105.12]},
])
def test_current_listing_changes_revoke_the_old_image_binding(artwork, clients, change):
    from estimoto_plus.discovery_models import PublicListing
    entry, _, _ = artwork
    client, _ = clients
    setup(client)
    rows = client.get('/v1/discovery', headers=h('alice')).json()['providers']
    url = next(r['media']['url'] for r in rows if r['source_id'] == 'node:1')
    with client.app.state.session_factory() as db:
        row = db.get(PublicListing, 'node:1')
        row.value = {**row.value, **change}
        db.commit()
    assert client.get(url).status_code == 404


@pytest.mark.parametrize('revocation', ['expired_review', 'future_review', 'removed_review', 'expired_listing'])
def test_public_artwork_requires_current_business_and_listing(artwork, clients, monkeypatch, revocation):
    from datetime import timedelta
    from estimoto_plus import reviewed_shops
    from estimoto_plus.discovery_models import PublicListing
    from estimoto_plus.models import now
    client, _ = clients
    setup(client)
    rows = client.get('/v1/discovery', headers=h('alice')).json()['providers']
    url = next(r['media']['url'] for r in rows if r['source_id'] == 'node:1')
    assert client.get(url).status_code == 200
    entries = reviewed_shops.catalog()
    if revocation == 'expired_listing':
        with client.app.state.session_factory() as db:
            db.get(PublicListing, 'node:1').fetched_at = now() - timedelta(days=8)
            db.commit()
    else:
        if revocation == 'removed_review':
            entries.pop('node:1')
        else:
            days = -91 if revocation == 'expired_review' else 1
            entries['node:1']['checked_at'] = (now().date() + timedelta(days=days)).isoformat()
        monkeypatch.setattr(reviewed_shops, 'catalog', lambda: entries)
    assert client.get(url).status_code == 404


@pytest.mark.parametrize('favorite_public', [False, True])
def test_reviewed_logo_dedupe_keeps_image_identity_and_partner_actions(artwork, clients, favorite_public):
    from estimoto_plus.discovery_provider import normalize_listing
    from test_discovery import partner
    entry, _, write = artwork
    client, _ = clients
    vehicle, stub = setup(client)
    provider_id = partner(client)
    stub.elements = [stub.shop(1, 'Demolition Dent fixture', {
        'phone': '3035550100', 'service:vehicle:pdr': 'yes',
        'addr:housenumber': '1', 'addr:street': 'Example St',
        'addr:city': 'Denver', 'addr:state': 'CO', 'addr:postcode': '80221',
    })]
    public = normalize_listing(stub.elements[0])
    write(shops=[{**entry, 'name': public['name'], 'address': public['address']}])
    params = {'vehicle_id': vehicle, 'specialty': 'pdr'}
    assert client.get('/v1/discovery', headers=h('alice'), params=params).status_code == 200
    if favorite_public:
        saved = client.put('/v1/discovery/favorites/pdr', headers=h('alice'), json={
            'vehicle_id': vehicle, 'source': 'openstreetmap', 'source_id': 'node:1'})
        assert saved.status_code == 200
    rows = client.get('/v1/discovery', headers=h('alice'), params=params).json()['providers']
    assert len(rows) == 1
    merged = rows[0]
    assert merged['id'] == provider_id and merged['source'] == 'estimoto'
    assert merged['source_id'] == 'demolition-fixture'
    assert merged['request_modes'] == ['shop_visit']
    assert merged['media'] == media.listing_media(public)
    assert merged['media_identity'] == {'source': 'openstreetmap', 'source_id': 'node:1'}
    assert client.get(merged['media']['url']).status_code == 200
    assert merged['favorite'] is favorite_public
    assert merged['favorite_references'] == ([saved.json()] if favorite_public else [])
