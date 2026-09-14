from test_discovery import clients, setup
from test_api import h
from estimoto_plus.official_shops import catalog as real_catalog
from estimoto_plus import official_shops


def test_bluewater_available_without_map_listing_and_favorite_roundtrip(clients, monkeypatch):
    monkeypatch.setattr(official_shops, "catalog", real_catalog)
    c,_ = clients
    vehicle,stub=setup(c)
    c.put(f'/v1/vehicles/{vehicle}',headers=h('alice'),json={'make':'Audi'})
    result=c.get('/v1/discovery',headers=h('alice'),params={'postal_code':'80229','vehicle_id':vehicle,'q':'Bluewater'}).json()
    shop=next(r for r in result['providers'] if r['name']=='Bluewater Performance')
    assert shop['source']=='official_website'
    assert shop['vehicle_match']['status']=='listed_make'
    assert shop['phone']=='+13038007193' and shop['request_modes']==[]
    assert c.put('/v1/discovery/favorites/mechanical',headers=h('alice'),json={
        'vehicle_id':vehicle,'source':shop['source'],'source_id':shop['source_id']}).status_code==200
    assert c.get('/v1/discovery/favorites',headers=h('alice'),params={'vehicle_id':vehicle}).json()[0]['source_id']==shop['source_id']


def test_official_shop_is_not_a_nationwide_or_mobile_result(clients, monkeypatch):
    monkeypatch.setattr(official_shops, "catalog", real_catalog)
    from estimoto_plus import discovery
    c,_=clients
    _,stub=setup(c)
    # A remote search center must not include a Denver catalog entry.
    import httpx
    original=stub.__call__
    def remote(request):
        if request.url.host=='api.zippopotam.us':
            return httpx.Response(200,json={'post code':'10001','country abbreviation':'US','places':[{'latitude':'40.75','longitude':'-73.99'}]})
        return original(request)
    c.app.state.discovery_transport=httpx.MockTransport(remote)
    result=c.get('/v1/discovery',headers=h('alice'),params={'postal_code':'10001','q':'Bluewater'}).json()
    assert result['providers']==[]
