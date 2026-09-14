from test_discovery import clients, setup, partner
from test_api import h


def test_unreviewed_public_shop_can_be_found_and_saved(clients):
    c, _ = clients
    vehicle, stub = setup(c)
    stub.unreviewed_ids.add(1)
    rows = c.get('/v1/discovery', headers=h('alice'), params={'q': 'General repair'}).json()['providers']
    assert [r['source_id'] for r in rows] == ['node:1']
    assert rows[0]['verification']['status'] == 'public_listing'
    assert rows[0]['request_modes'] == []
    assert c.put('/v1/discovery/favorites/mechanical', headers=h('alice'), json={
        'vehicle_id':vehicle, 'source':'openstreetmap','source_id':'node:1'}).status_code == 200


def test_make_matching_and_name_search_precede_result_cap(clients):
    c, _ = clients
    vehicle, stub = setup(c)
    c.put(f'/v1/vehicles/{vehicle}',headers=h('alice'),json={'make':'Audi'})
    partner(c)
    rows = c.get('/v1/discovery',headers=h('alice'),params={'vehicle_id':vehicle}).json()['providers']
    assert rows[0]['name'] == 'Audi specialist'
    rows = c.get('/v1/discovery',headers=h('alice'),params={'vehicle_id':vehicle,'make_only':True}).json()['providers']
    assert [r['name'] for r in rows] == ['Audi specialist']
    rows = c.get('/v1/discovery',headers=h('alice'),params={'q':'no-such-shop'}).json()['providers']
    assert rows == []


def test_other_zip_does_not_change_profile(clients):
    c,_ = clients
    _,stub=setup(c)
    stub.unreviewed_ids.update([1,2])
    result=c.get('/v1/discovery',headers=h('alice'),params={'postal_code':'80221'}).json()
    assert result['postal_code']=='80221' and len(result['providers'])==2
    assert c.get('/v1/bootstrap',headers=h('alice')).json()['profile']['postal_code']=='80204'


def test_neighbor_zip_uses_recent_index_when_upstream_is_down(clients):
    from estimoto_plus.discovery_cache import zip_location
    c,_=clients
    _,stub=setup(c)
    assert c.get('/v1/discovery',headers=h('alice')).status_code==200
    zip_location(c.app.state.session_factory,c.app.state.discovery_transport,'80221')
    stub.fail=True
    result=c.get('/v1/discovery',headers=h('alice'),params={'postal_code':'80221'}).json()
    assert result['status']=='stale'
    assert len(result['providers'])==2


def test_vehicle_matching_changes_with_owned_vehicle_make(clients):
    c,_=clients
    vehicle,stub=setup(c)
    stub.elements += [stub.shop(3,'Toyota care',{'service:vehicle:brand':'Toyota'}),
                      stub.shop(4,'BMW care',{'service:vehicle:brand':'BMW'})]
    for make,expected in [('Audi','Audi specialist'),('Toyota','Toyota care'),('BMW','BMW care')]:
        c.put(f'/v1/vehicles/{vehicle}',headers=h('alice'),json={'make':make})
        params={'vehicle_id':vehicle,'make_only':True}
        rows=c.get('/v1/discovery',headers=h('alice'),params=params).json()['providers']
        assert [r['name'] for r in rows]==[expected]
        assert rows[0]['vehicle_match']['make']==make
    c.put(f'/v1/vehicles/{vehicle}',headers=h('alice'),json={'make':'Honda'})
    assert c.get('/v1/discovery',headers=h('alice'),params=params).json()['providers']==[]
    # Broad search still offers general repair when make coverage is unknown.
    rows=c.get('/v1/discovery',headers=h('alice'),params={'vehicle_id':vehicle}).json()['providers']
    assert len(rows)==4
    assert all(r['vehicle_match']['status']=='not_verified' for r in rows)


def test_secondary_map_endpoint_recovers_cold_zip_and_shares_budget(clients):
    import httpx
    from estimoto_plus.discovery_models import DirectoryBudget
    from estimoto_plus.models import now
    c,_=clients
    _,stub=setup(c)
    calls=[]
    def transport(request):
        calls.append(request.url.host)
        if request.url.host=='overpass-api.de':
            return httpx.Response(503,content=b'busy')
        if request.url.host=='overpass.private.coffee':
            return httpx.Response(200,json={'elements':stub.elements})
        return stub(request)
    c.app.state.discovery_transport=httpx.MockTransport(transport)
    result=c.get('/v1/discovery',headers=h('alice')).json()
    assert result['status']=='ready' and len(result['providers'])==2
    assert calls.count('overpass-api.de')==calls.count('overpass.private.coffee')==1
    with c.app.state.session_factory() as db:
        assert db.get(DirectoryBudget,now().date().isoformat()).attempts==2
    previous=list(calls)
    assert c.get('/v1/discovery',headers=h('alice')).json()['status']=='ready'
    assert calls==previous


def test_secondary_endpoint_cannot_bypass_daily_budget(clients):
    import httpx
    c,_=clients
    _,stub=setup(c)
    c.app.state.settings.discovery_daily_requests=1
    calls=[]
    def transport(request):
        calls.append(request.url.host)
        if request.url.host=='api.zippopotam.us':
            return stub(request)
        return httpx.Response(503,content=b'busy')
    c.app.state.discovery_transport=httpx.MockTransport(transport)
    assert c.get('/v1/discovery',headers=h('alice')).json()['status']=='unavailable'
    assert calls.count('overpass-api.de')==1
    assert 'overpass.private.coffee' not in calls
