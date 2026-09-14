from copy import deepcopy
from datetime import timedelta
import json

import pytest

from estimoto_plus import reviewed_shops as review
from estimoto_plus.models import now
from test_api import h
from test_discovery import clients, setup


def test_unreviewed_shop_keeps_public_label_in_directory_assistant_and_favorites(clients):
    client, _ = clients
    vehicle, stub = setup(client)
    stub.unreviewed_ids.add(1)
    rows = client.get('/v1/discovery', headers=h('alice')).json()['providers']
    assert {r['source_id'] for r in rows} == {'node:1', 'node:2'}
    rows.sort(key=lambda r: r['source_id'], reverse=True)
    assert rows[0]['verification']['status'] == 'contact_confirmed'
    assert rows[0]['website'] == 'https://fixture.example/'
    result = client.post('/v1/assistant', headers=h('alice'), json={
        'message': 'Find a mechanic nearby', 'vehicle_id': vehicle}).json()
    assert next(r for r in result['providers'] if r['source_id'] == 'node:1')['verification']['status'] == 'public_listing'
    assert client.put('/v1/discovery/favorites/mechanical', headers=h('alice'), json={
        'vehicle_id': vehicle, 'source': 'openstreetmap', 'source_id': 'node:1'}).status_code == 200


@pytest.fixture
def reviewed_catalog(tmp_path, monkeypatch):
    row = {'source': 'openstreetmap', 'source_id': 'node:42', 'name': 'Reviewed Shop',
           'address': '1 Known Street', 'point': [39.7, -105.0], 'phone': '3035550000', 'listed_makes': []}
    entry = {**row, 'business_verified': True, 'source_point': row['point'],
             'verified_address': '1 Known Street, Denver CO 80204',
             'website': 'https://shop.example/branch?location=42', 'phone': '+13035550142',
             'verification_url': 'https://shop.example/branch?location=42',
             'checked_at': now().date().isoformat(), 'specialties': ['mechanical'],
             'description': 'Engine and brake repairs.', 'evidence': 'Official exact location contact page.'}
    monkeypatch.setattr(review.media, 'ASSET_DIR', tmp_path)
    def write(value):
        (tmp_path / 'catalog.json').write_text(json.dumps({'schema': 1, 'businesses': [value]}))
        review.catalog.cache_clear()
    write(entry)
    yield row, entry, write
    review.catalog.cache_clear()


def test_contact_verification_is_independent_of_artwork_and_replaces_stale_contact(reviewed_catalog):
    row, entry, _ = reviewed_catalog
    result = review.verified_listing(row)
    assert result['phone'] == '+13035550142' and result['website'] == entry['website']
    assert result['verification']['address'] == entry['verified_address']
    assert 'media' not in result
    assert 'google_rating' not in result
    assert row['phone'] == '3035550000'


@pytest.mark.parametrize('change', [
    {'name': 'Replacement Business'}, {'address': 'Moved Street'}, {'point': [39.8, -105.0]},
    {'source_id': 'node:43'}, {'source': 'estimoto'},
])
def test_identity_changes_revoke_verification(reviewed_catalog, change):
    row, _, _ = reviewed_catalog
    assert review.verified_listing({**row, **change}) is None


@pytest.mark.parametrize('change', [
    {'business_verified': False}, {'phone': ''}, {'website': 'https://127.0.0.1/'},
    {'verification_url': 'javascript:alert(1)'}, {'specialties': ['invented']},
    {'evidence': ''}, {'source_point': [99, 0]}, {'website': 'https://shop.example/?\nsecret'},
])
def test_incomplete_business_verification_fails_closed(reviewed_catalog, change):
    row, entry, write = reviewed_catalog
    write({**entry, **change})
    assert review.verified_listing(row) is None


def test_reviews_expire_and_future_or_invalid_review_dates_do_not_qualify(reviewed_catalog):
    row, entry, write = reviewed_catalog
    for checked in ((now().date() - timedelta(days=91)).isoformat(),
                    (now().date() + timedelta(days=1)).isoformat(), 'not-a-date'):
        write({**entry, 'checked_at': checked})
        assert review.verified_listing(row) is None


def test_packaged_catalog_has_twenty_to_thirty_verified_shops_and_exact_artwork():
    from estimoto_plus import shop_media_catalog as media
    from pathlib import Path
    data = json.loads((Path(review.__file__).parent / 'shop_media' / 'catalog.json').read_text())
    assert 20 <= len(data['businesses']) <= 30
    assert len({r['source_id'] for r in data['businesses']}) == len(data['businesses'])
    images = {r['source_id']: r for r in data['shops']}
    for entry in data['businesses']:
        assert review.valid_business(entry), entry['name']
        assert images[entry['source_id']]['name'] == entry['name']
        assert media.valid_entry(images[entry['source_id']]), entry['name']
        assert not entry.get('google_rating')
