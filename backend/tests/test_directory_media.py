"""Media on public directory cards is sourced, bounded, and never customer supplied."""
import httpx

from test_api import h
from test_discovery import DirectoryStub, clients, partner, setup


BRIDGE = {'X-Bridge-Key': 'bridge-secret'}
ORIGIN = 'https://bridge.example'


def logo(source_id='shop-42', url=None):
    return {
        'url': url or f'{ORIGIN}/public/plus/providers/{source_id}/logo',
        'kind': 'logo', 'attribution': 'Published Repair Shop',
        'source_url': 'https://www.estimoto.io',
    }


def publish(client, *, source_id='shop-42', media=None, visible=True):
    return client.post('/v1/bridge/providers', headers=BRIDGE, json={
        'source_id': source_id, 'name': 'Published Repair Shop', 'kind': 'shop',
        'specialties': ['collision'], 'postal_codes': ['80204'],
        'address': '1 Example Street Denver CO 80204',
        'public_visible': visible, 'accepting_requests': visible,
        'media': media,
    })


def test_owner_published_logo_is_shared_and_opt_out_removes_it(clients):
    client, _ = clients
    vehicle, _ = setup(client)
    published = publish(client, media=logo())
    assert published.status_code == 200, published.text
    provider = published.json()
    assert provider['source_id'] == 'shop-42'
    assert provider['media'] == logo()
    assert client.get('/v1/providers', headers=h('alice')).json()[0]['media'] == logo()
    assert client.get('/v1/bootstrap', headers=h('alice')).json()['providers'][0]['media'] == logo()
    listing = client.get('/v1/discovery', headers=h('alice'), params={'vehicle_id': vehicle}).json()['providers'][0]
    assert listing['source'] == 'estimoto' and listing['media'] == logo()
    assert client.get('/v1/discovery', headers=h('bob'), params={'vehicle_id': vehicle}).status_code == 404
    assert publish(client, media=logo(), visible=False).status_code == 200
    assert client.get('/v1/providers', headers=h('alice')).json() == []
    assert all(row['source'] != 'estimoto' for row in client.get('/v1/discovery', headers=h('alice')).json()['providers'])


def test_partner_media_rejects_foreign_private_or_mismatched_urls(clients):
    client, _ = clients
    for url in (
        'http://bridge.example/public/plus/providers/shop-42/logo',
        'https://evil.example/public/plus/providers/shop-42/logo',
        'https://bridge.example/media/object?ref=private',
        'https://bridge.example/public/plus/providers/other/logo',
        'https://bridge.example/public/plus/providers/shop-42/logo?token=secret',
        'https://bridge.example/public/plus/providers/shop-42/logo#private',
    ):
        response = publish(client, media=logo(url=url))
        assert response.status_code == 422, url
    assert client.get('/v1/providers', headers=h('alice')).json() == []


def test_catalog_pull_accepts_only_fixed_owner_logo_and_clears_removed_logo(clients):
    client, _ = clients
    catalog = {'media': logo()}

    def receiver(request):
        if request.url.path.endswith('/providers'):
            return httpx.Response(200, json=[{
                'source_id': 'shop-42', 'name': 'Published Repair Shop', 'kind': 'shop',
                'specialties': ['pdr'], 'postal_codes': ['80204'],
                'public_visible': True, 'accepting_requests': True,
                'media': catalog['media'],
            }])
        return httpx.Response(503)

    client.app.state.bridge_transport = httpx.MockTransport(receiver)
    assert client.post('/v1/bridge/sync', headers=BRIDGE).json()['providers_synced'] is True
    assert client.get('/v1/providers', headers=h('alice')).json()[0]['media'] == logo()
    catalog['media'] = logo(url='https://evil.example/public/plus/providers/shop-42/logo')
    assert client.post('/v1/bridge/sync', headers=BRIDGE).json()['providers_synced'] is False
    assert client.get('/v1/providers', headers=h('alice')).json()[0]['media'] == logo()
    catalog['media'] = None
    assert client.post('/v1/bridge/sync', headers=BRIDGE).json()['providers_synced'] is True
    assert client.get('/v1/providers', headers=h('alice')).json()[0]['media'] is None


def test_commons_file_media_requires_creator_license_and_stays_cached(clients):
    client, _ = clients
    _, stub = setup(client)
    stub.elements = [
        stub.shop(1, 'Documented shop', {'wikimedia_commons': 'File:Documented shop.jpg'}),
        stub.shop(2, 'Unlicensed shop', {'wikimedia_commons': 'File:Unlicensed shop.jpg'}),
        stub.shop(3, 'Arbitrary website image', {'image': 'https://evil.example/shop.jpg'}),
        stub.shop(4, 'Commons category', {'wikimedia_commons': 'Category:Repair shops'}),
    ]
    original = stub.__call__

    def transport(request):
        if request.url.host == 'commons.wikimedia.org':
            assert request.method == 'GET'
            assert request.url.path == '/w/api.php'
            assert 'Documented shop.jpg' in request.url.params['titles']
            assert 'Unlicensed shop.jpg' in request.url.params['titles']
            assert 'evil.example' not in str(request.url)
            return httpx.Response(200, json={'query': {'pages': [
                {'title': 'File:Documented shop.jpg', 'imageinfo': [{'mime': 'image/jpeg', 'extmetadata': {
                    'Artist': {'value': '<a href="https://commons.wikimedia.org/wiki/User:Jane">Jane Doe</a>'},
                    'LicenseShortName': {'value': 'CC BY-SA 4.0'},
                }}]},
                {'title': 'File:Unlicensed shop.jpg', 'imageinfo': [{'mime': 'image/jpeg', 'extmetadata': {
                    'Artist': {'value': 'Unknown'},
                }}]},
            ]}})
        return original(request)

    client.app.state.discovery_transport = httpx.MockTransport(transport)
    rows = client.get('/v1/discovery', headers=h('alice')).json()['providers']
    by_name = {row['name']: row for row in rows}
    media = by_name['Documented shop']['media']
    assert media == {
        'url': 'https://commons.wikimedia.org/wiki/Special:Redirect/file/Documented_shop.jpg?width=320',
        'kind': 'photo', 'attribution': 'Jane Doe · CC BY-SA 4.0',
        'source_url': 'https://commons.wikimedia.org/wiki/File:Documented_shop.jpg',
    }
    assert all(by_name[name]['media'] is None for name in ('Unlicensed shop', 'Arbitrary website image', 'Commons category'))
    assert len([request for request in stub.calls if request.url.host == 'overpass-api.de']) == 1
    assert client.get('/v1/discovery', headers=h('alice')).status_code == 200
    assert len([request for request in stub.calls if request.url.host == 'overpass-api.de']) == 1


def test_commons_metadata_failure_does_not_discard_directory(clients):
    client, _ = clients
    _, stub = setup(client)
    stub.elements = [stub.shop(1, 'Real listing', {'wikimedia_commons': 'File:Real listing.jpg'})]
    original = stub.__call__
    client.app.state.discovery_transport = httpx.MockTransport(
        lambda request: httpx.Response(503) if request.url.host == 'commons.wikimedia.org' else original(request))
    response = client.get('/v1/discovery', headers=h('alice'))
    assert response.status_code == 200
    assert response.json()['status'] == 'ready'
    assert response.json()['providers'][0]['media'] is None


def test_commons_lookup_is_one_fixed_origin_batch_of_at_most_twenty():
    from estimoto_plus.discovery_provider import fetch_listings
    stub = DirectoryStub()
    stub.elements = [stub.shop(i, f'Shop {i}', {'wikimedia_commons': f'File:Shop {i}.jpg'}) for i in range(1, 42)]
    calls = []

    def transport(request):
        if request.url.host == 'commons.wikimedia.org':
            calls.append(request)
            assert request.url.path == '/w/api.php'
            assert len(request.url.params['titles'].split('|')) == 20
            return httpx.Response(200, json={'query': {'pages': []}})
        return stub(request)

    meter = {'body_bytes': 0}
    data = fetch_listings([39.75, -105.02], httpx.MockTransport(transport), limit=512 * 1024, meter=meter)
    assert len(data['listings']) == 41
    assert all(row['media'] is None for row in data['listings'])
    assert len(calls) == 1 and meter['body_bytes'] < 512 * 1024


def test_unknown_creator_is_not_treated_as_verified_credit():
    from estimoto_plus.directory_media import verified_commons_media
    title = 'File:Unknown shop.jpg'
    response = {'query': {'pages': [{'title': title, 'imageinfo': [{
        'mime': 'image/jpeg', 'extmetadata': {
            'Artist': {'value': 'Unknown'}, 'LicenseShortName': {'value': 'CC BY 4.0'},
        },
    }]}]}}
    assert verified_commons_media([title], None, lambda *args, **kwargs: response,
                                  limit=65536, meter={'body_bytes': 0}) == {}


def test_same_location_public_photo_survives_partner_dedupe(clients, monkeypatch):
    from estimoto_plus import discovery
    from estimoto_plus.discovery_provider import normalize_listing
    from estimoto_plus.models import now
    client, _ = clients
    _, stub = setup(client)
    provider_id = partner(client)
    stub.elements = [stub.shop(1, 'Demolition Dent fixture', {
        'phone': '3035550100', 'service:vehicle:pdr': 'yes',
        'addr:housenumber': '1', 'addr:street': 'Example St',
        'addr:city': 'Denver', 'addr:state': 'CO', 'addr:postcode': '80221',
    })]
    row = normalize_listing(stub.elements[0])
    row['media'] = {'url': 'https://commons.wikimedia.org/wiki/Special:Redirect/file/Shop.jpg?width=320',
                    'kind': 'photo', 'attribution': 'Jane Doe · CC BY 4.0',
                    'source_url': 'https://commons.wikimedia.org/wiki/File:Shop.jpg'}
    monkeypatch.setattr(discovery, 'public_directory', lambda *_, **kw: ({'listings': [row]}, 'ready', now()))
    matched = [r for r in client.get('/v1/discovery', headers=h('alice')).json()['providers'] if r['id'] == provider_id]
    assert len(matched) == 1
    assert matched[0]['request_modes'] == ['shop_visit']
    assert matched[0]['media'] == row['media']
    assert matched[0]['media_identity'] == {'source': 'openstreetmap', 'source_id': 'node:1'}


def test_preupgrade_cached_public_listing_has_explicit_null_media(clients, monkeypatch):
    from estimoto_plus import discovery
    from estimoto_plus.discovery_provider import normalize_listing
    from estimoto_plus.models import now
    client, _ = clients
    _, stub = setup(client)
    stub.elements = [stub.shop(1, 'Cached old listing')]
    row = normalize_listing(stub.elements[0])
    row.pop('media')
    monkeypatch.setattr(discovery, 'public_directory', lambda *_, **kw: ({'listings': [row]}, 'stale', now()))
    response = client.get('/v1/discovery', headers=h('alice'))
    assert response.status_code == 200
    assert response.json()['providers'][0]['media'] is None
