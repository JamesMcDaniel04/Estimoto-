import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from threading import Barrier, Event, Lock
from types import SimpleNamespace

from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from estimoto_plus import app as app_module, auth, auth_cache
from estimoto_plus.auth import create_auth_client, current_customer, verify_supabase
from estimoto_plus.auth_cache import VerifiedAuthCache
from estimoto_plus.config import Settings


def encode(value):
    data = value if isinstance(value, bytes) else json.dumps(value).encode()
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def jwt(subject='alice', expiry=2_000_000_100, *, signature=b'verified-signature'):
    return '.'.join((encode({'alg': 'HS256', 'typ': 'JWT'}),
                     encode({'sub': subject, 'exp': expiry}), encode(signature)))


def identity(subject='alice', **changes):
    return {'id': subject, 'email': subject + '@example.test', 'confirmed_at': 'ok', **changes}


@pytest.fixture
def clock(monkeypatch):
    value = SimpleNamespace(wall=2_000_000_000.0, mono=100.0)
    monkeypatch.setattr(auth_cache, 'wall_time', lambda: value.wall)
    monkeypatch.setattr(auth_cache, 'monotonic', lambda: value.mono)
    return value


def test_read_cache_uses_complete_token_hash_and_independent_minimal_identities(clock):
    cache = VerifiedAuthCache()
    tokens = [jwt(), jwt(signature=b'another-session'), jwt('bob')]
    calls = []
    original = identity(user_metadata={'private': 'not retained'})
    def load(token):
        calls.append(token)
        return identity('bob') if token == tokens[2] else original
    for token in tokens:
        assert cache.verify(token, lambda: load(token), read_only=True)['id'] == (
            'bob' if token == tokens[2] else 'alice')
    original['email'] = 'changed-outside-cache@example.test'
    first = cache.verify(tokens[0], lambda: load(tokens[0]), read_only=True)
    assert first == {'id': 'alice', 'email': 'alice@example.test', 'confirmed_at': True}
    first['id'] = 'bob'
    assert cache.verify(tokens[0], lambda: load(tokens[0]), read_only=True)['id'] == 'alice'
    assert len(calls) == 3
    assert set(cache._entries) == {hashlib.sha256(t.encode()).hexdigest() for t in tokens}
    assert all(t not in repr(cache.__dict__) for t in tokens)
    assert 'private' not in repr(cache.__dict__)
    cache.verify(tokens[0], lambda: load(tokens[0]), read_only=False)
    assert len(calls) == 4
    assert set(cache._entries) == {hashlib.sha256(t.encode()).hexdigest() for t in tokens[1:]}


def test_revocation_is_seen_at_the_fifteen_second_deadline_and_never_error_cached(clock):
    cache = VerifiedAuthCache()
    token = jwt()
    calls, revoked = [], False
    def load():
        calls.append(True)
        if revoked:
            raise HTTPException(401, 'Sign in to continue.')
        return identity()
    cache.verify(token, load, read_only=True)
    revoked = True
    clock.mono += 14.999
    clock.wall += 14.999
    assert cache.verify(token, load, read_only=True)['id'] == 'alice'
    assert len(calls) == 1
    clock.mono += .001
    clock.wall += .001
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            cache.verify(token, load, read_only=True)
        assert error.value.status_code == 401
    assert len(calls) == 3 and not cache._entries and not cache._pending


@pytest.mark.parametrize('advance', ['jwt_expiry', 'clock_rollback', 'slow_verification'])
def test_expiry_caps_ttl_and_verification_latency_or_clock_rollback_cannot_extend_it(clock, advance):
    cache = VerifiedAuthCache()
    token = jwt(expiry=clock.wall + 3 if advance == 'jwt_expiry' else clock.wall + 100)
    calls = []
    def load():
        calls.append(True)
        if advance == 'slow_verification':
            clock.mono += 15
        return identity()
    cache.verify(token, load, read_only=True)
    if advance == 'jwt_expiry':
        clock.wall += 3
    elif advance == 'clock_rollback':
        clock.wall -= 60
        clock.mono += 15
    cache.verify(token, load, read_only=True)
    assert len(calls) == 2


def test_lru_eviction_is_bounded_and_retains_recently_used_tokens(clock):
    cache = VerifiedAuthCache(max_entries=2)
    calls = []
    def read(subject):
        def load():
            calls.append(subject)
            return identity(subject)
        return cache.verify(jwt(subject), load, read_only=True)
    read('alice')
    read('bob')
    read('alice')
    read('carol')
    assert len(cache._entries) == 2
    read('alice')
    read('bob')
    assert calls == ['alice', 'bob', 'carol', 'bob']


@pytest.mark.parametrize('token', [
    'opaque', 'bad.jwt.structure', 'a' * 16385,
    jwt(expiry=True), jwt(expiry='2000000100'), jwt(expiry=float('nan')),
    jwt().rsplit('.', 1)[0] + '.',
    '.'.join((encode({'alg': 'none'}), encode({'sub': 'alice', 'exp': 2_000_000_100}), encode(b'sig'))),
    '.'.join((encode({'alg': 'HS256'}), encode({'sub': 'alice'}), encode(b'sig'))),
    '.'.join((encode({'alg': 'HS256'}), encode(b'{"sub":"alice","exp":2000000100,"exp":2000000200}'), encode(b'sig'))),
])
def test_opaque_or_malformed_jwt_still_verifies_upstream_without_caching(clock, token):
    cache, calls = VerifiedAuthCache(), []
    def load():
        calls.append(True)
        return identity()
    assert cache.verify(token, load, read_only=True)['id'] == 'alice'
    assert cache.verify(token, load, read_only=True)['id'] == 'alice'
    assert len(calls) == 2 and not cache._entries and not cache._pending


@pytest.mark.parametrize('result', [
    None, {}, identity(is_anonymous=True), identity(confirmed_at=None),
    identity(email=''), identity(email='x' * 321), identity('different-subject'),
    identity(_demo=True), identity(id=['alice']),
])
def test_unconfirmed_anonymous_invalid_or_mismatched_identities_are_never_cached(clock, result):
    cache, calls = VerifiedAuthCache(), []
    def load():
        calls.append(True)
        return result
    for _ in range(2):
        assert cache.verify(jwt(), load, read_only=True) is result
    assert len(calls) == 2 and not cache._entries and not cache._pending


@pytest.mark.parametrize('status', [401, 503])
def test_upstream_errors_do_not_fill_cache_or_leave_pending_state(clock, status):
    cache, calls = VerifiedAuthCache(), []
    def load():
        calls.append(True)
        raise HTTPException(status, 'Authentication unavailable')
    for _ in range(2):
        with pytest.raises(HTTPException):
            cache.verify(jwt(), load, read_only=True)
    assert len(calls) == 2 and not cache._entries and not cache._pending


def test_same_token_concurrent_reads_share_one_verification(clock, monkeypatch):
    cache, started, release, barrier = VerifiedAuthCache(), Event(), Event(), Barrier(8)
    calls, lock, all_waiting, waiters = [], Lock(), Event(), []
    original_flight = auth_cache._Flight
    class ObservedEvent:
        def __init__(self):
            self.event = Event()
        def wait(self, timeout):
            with lock:
                waiters.append(True)
                if len(waiters) == 7:
                    all_waiting.set()
            return self.event.wait(timeout)
        def set(self):
            self.event.set()
    monkeypatch.setattr(auth_cache, '_Flight', lambda timestamp: original_flight(timestamp, done=ObservedEvent()))
    def load():
        with lock:
            calls.append(True)
        started.set()
        assert release.wait(3)
        return identity()
    def read():
        barrier.wait(timeout=3)
        return cache.verify(jwt(), load, read_only=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(read) for _ in range(8)]
        assert started.wait(3)
        assert all_waiting.wait(3)  # All seven followers overlap the upstream call.
        assert list(cache._pending) == [hashlib.sha256(jwt().encode()).hexdigest()]
        release.set()
        assert [f.result(timeout=3)['id'] for f in futures] == ['alice'] * 8
    assert calls == [True] and not cache._pending


def test_pending_capacity_is_bounded_and_other_accounts_verify_independently(clock):
    cache, started, release = VerifiedAuthCache(max_pending=1), Event(), Event()
    def alice():
        started.set()
        assert release.wait(3)
        return identity()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(cache.verify, jwt(), alice, read_only=True)
        assert started.wait(3)
        calls = []
        def bob():
            calls.append(True)
            return identity('bob')
        for _ in range(2):
            assert cache.verify(jwt('bob'), bob, read_only=True)['id'] == 'bob'
        assert len(cache._pending) == 1 and len(calls) == 2
        release.set()
        assert pending.result(timeout=3)['id'] == 'alice'
    assert not cache._pending


def test_fresh_write_invalidates_and_prevents_an_older_read_repopulating_cache(clock):
    cache, started, release = VerifiedAuthCache(), Event(), Event()
    def read():
        started.set()
        assert release.wait(3)
        return identity()
    def revoked():
        raise HTTPException(401, 'Sign in to continue.')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(cache.verify, jwt(), read, read_only=True)
        assert started.wait(3)
        with pytest.raises(HTTPException):
            cache.verify(jwt(), revoked, read_only=False)
        release.set()
        pending.result(timeout=3)
    assert not cache._entries
    with pytest.raises(HTTPException):
        cache.verify(jwt(), revoked, read_only=True)


def test_write_completion_also_invalidates_reads_started_during_verification(clock):
    cache, started, release = VerifiedAuthCache(), Event(), Event()
    def write():
        started.set()
        assert release.wait(3)
        return identity()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(cache.verify, jwt(), write, read_only=False)
        assert started.wait(3)
        cache.verify(jwt(), identity, read_only=True)
        assert len(cache._entries) == 1
        release.set()
        pending.result(timeout=3)
    assert not cache._entries


def settings(tmp_path, name):
    return Settings(database_url=f'sqlite:///{tmp_path / (name + ".sqlite")}', environment='test',
                    supabase_url='https://auth.example', supabase_publishable_key='publishable',
                    worker_enabled=False, photo_dir=str(tmp_path / 'photos'))


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
def test_only_get_and_head_cache_and_mutations_detect_revocation_immediately(tmp_path, clock, method, caplog):
    caplog.set_level('DEBUG', logger='httpx')
    calls, revoked = [], False
    def transport(request):
        calls.append(request)
        return httpx.Response(401 if revoked else 200, json=identity())
    with httpx.Client(transport=httpx.MockTransport(transport)) as upstream:
        app = app_module.create_app(settings(tmp_path, method), auth_client=upstream)
        @app.api_route('/auth-fixture', methods=['GET', 'HEAD', method])
        def endpoint(customer=Depends(current_customer)):
            return {'id': customer.id}
        with TestClient(app) as client:
            headers = {'Authorization': 'Bearer ' + jwt()}
            assert client.get('/auth-fixture', headers=headers).json() == {'id': 'alice'}
            assert client.head('/auth-fixture', headers=headers).status_code == 200
            revoked = True
            assert client.get('/auth-fixture', headers=headers).status_code == 200
            assert len(calls) == 1
            assert client.request(method, '/auth-fixture', headers=headers).status_code == 401
            assert client.get('/auth-fixture', headers=headers).status_code == 401
            assert len(calls) == 3
            assert all(str(r.url) == 'https://auth.example/auth/v1/user' for r in calls)
            assert all(r.headers['authorization'] == 'Bearer ' + jwt() for r in calls)
            assert not app.state.auth_cache._entries
        assert not upstream.is_closed  # Injected clients belong to their caller.
    assert jwt() not in caplog.text


def test_owned_auth_pool_does_not_retain_or_forward_one_accounts_cookies(tmp_path, monkeypatch):
    constructor, calls = httpx.Client, []
    def transport(request):
        calls.append(request)
        user = 'alice' if request.headers['authorization'] == 'Bearer alice-token' else 'bob'
        return httpx.Response(200, json=identity(user), headers={
            'Set-Cookie': f'session={user}-private-session; Path=/; Secure; HttpOnly'})
    monkeypatch.setattr(auth.httpx, 'Client', lambda **kwargs: constructor(
        **kwargs, transport=httpx.MockTransport(transport)))
    with create_auth_client() as pooled:
        for user in ('alice', 'bob', 'alice'):
            result = verify_supabase(settings(tmp_path, 'cookies'), user + '-token', pooled)
            assert result['id'] == user
        assert not list(pooled.cookies.jar)
    assert len(calls) == 3 and all('cookie' not in r.headers for r in calls)


@pytest.mark.parametrize('limit', ['ttl', 'jwt_expiry'])
def test_api_rechecks_revocation_at_read_ttl_or_earlier_jwt_expiry(tmp_path, clock, limit):
    calls, revoked = [], False
    def transport(_):
        calls.append(True)
        return httpx.Response(401 if revoked else 200, json=identity())
    seconds = 15 if limit == 'ttl' else 2
    token = jwt(expiry=clock.wall + (100 if limit == 'ttl' else seconds))
    with httpx.Client(transport=httpx.MockTransport(transport)) as upstream:
        app = app_module.create_app(settings(tmp_path, limit), auth_client=upstream)
        with TestClient(app) as client:
            headers = {'Authorization': 'Bearer ' + token}
            assert client.get('/v1/bootstrap', headers=headers).status_code == 200
            revoked = True
            assert client.get('/v1/bootstrap', headers=headers).status_code == 200
            clock.wall += seconds
            clock.mono += seconds
            assert client.get('/v1/bootstrap', headers=headers).status_code == 401
            assert len(calls) == 2


def test_real_apps_have_separate_caches_and_only_close_owned_pools(tmp_path, clock, monkeypatch):
    clients, calls = [], [0, 0]
    def factory():
        index = len(clients)
        def transport(_):
            calls[index] += 1
            return httpx.Response(200, json=identity(email=f'app-{index}@example.test'))
        client = httpx.Client(transport=httpx.MockTransport(transport))
        clients.append(client)
        return client
    monkeypatch.setattr(app_module, 'create_auth_client', factory)
    first = app_module.create_app(settings(tmp_path, 'first'))
    second = app_module.create_app(settings(tmp_path, 'second'))
    assert first.state.auth_cache is not second.state.auth_cache
    assert len(clients) == 2 and first.state.auth_client is clients[0]
    with TestClient(first) as a, TestClient(second) as b:
        for _ in range(2):
            assert a.get('/v1/bootstrap', headers={'Authorization': 'Bearer ' + jwt()}).json()['profile']['email'] == 'app-0@example.test'
            assert b.get('/v1/bootstrap', headers={'Authorization': 'Bearer ' + jwt()}).json()['profile']['email'] == 'app-1@example.test'
        assert calls == [1, 1] and len(first.state.auth_cache._entries) == 1
    assert all(c.is_closed for c in clients)
    assert not first.state.auth_cache._entries and not second.state.auth_cache._entries


def test_supplied_verifier_path_remains_uncached_and_does_not_create_a_pool(tmp_path, clock, monkeypatch):
    calls = []
    def verifier(token):
        calls.append(token)
        return identity()
    monkeypatch.setattr(app_module, 'create_auth_client', lambda: pytest.fail('Unneeded auth pool'))
    app = app_module.create_app(settings(tmp_path, 'injected'), auth_verifier=verifier)
    with TestClient(app) as client:
        for _ in range(2):
            assert client.get('/v1/bootstrap', headers={'Authorization': 'Bearer ' + jwt()}).status_code == 200
        assert calls == [jwt(), jwt()] and not app.state.auth_cache._entries
