#!/usr/bin/env python3
"""Guarded synthetic release proof. Default: validate local inputs, no network.

Never submits estimates, requests shops, invokes OCR/framing, or deletes accounts.
Run --self-test for isolated API/transport tests. Live use requires release-owner
authorization plus --run-live --expected-sha=<the deployed 40-character revision>.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from PIL import Image

TAG = 'guided-customer-release-20260913'
QA_DIR = Path.home() / '.config/estimoto-plus/qa'
ACCOUNT_FILE = QA_DIR / '2026-09-13-guided-customers.json'
CONFIG_FILE = QA_DIR.parent / 'service-env.json'
API_ORIGIN = 'https://estimoto-plus-api.fly.dev'
DEMOLITION_SOURCE = '516c3543-cf4e-43ca-b6b4-a505e1f67bd5'
MARKER = 'Guided release QA '
SYNTHETIC_VIN = '1HGCM82633A004352'
UUID_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
ALLOWED = {
    'GET': [r'/version', r'/ready', r'/v1/bootstrap', r'/v1/discovery', r'/v1/discovery/favorites',
            rf'/v1/estimates/{UUID_PATTERN}/capture',
            rf'/v1/estimates/{UUID_PATTERN}/photos/{UUID_PATTERN}'],
    'POST': [r'/v1/vehicles', r'/v1/estimates', rf'/v1/estimates/{UUID_PATTERN}/photos',
             rf'/v1/estimates/{UUID_PATTERN}/capture/photos',
             rf'/v1/estimates/{UUID_PATTERN}/capture/vin/confirm'],
    'PUT': [r'/v1/discovery/favorites/pdr'],
    'DELETE': [r'/v1/discovery/favorites/pdr'],
}


class SmokeFailure(Exception):
    """Only a fixed local check name; never a response, URL, credential or row."""


def require(condition, check):
    if not condition:
        raise SmokeFailure(check)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(UUID_PATTERN, value), 'invalid_resource_id')
    return str(UUID(value))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_private_json(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 128 * 1024,
                'private_input_permissions')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            value = json.loads(stream.read(128 * 1024 + 1))
        require(isinstance(value, dict), 'private_input_shape')
        return value
    finally:
        os.close(descriptor)


def validate_accounts(receipt):
    require(receipt.get('tag') == TAG, 'synthetic_account_tag')
    accounts = receipt.get('accounts')
    require(isinstance(accounts, list) and len(accounts) == 2, 'synthetic_account_count')
    require(all(isinstance(a, dict) for a in accounts), 'synthetic_account_shape')
    require({a.get('role') for a in accounts} == {'primary', 'foreign'}, 'synthetic_account_roles')
    result = {}
    for account in accounts:
        identifier(account.get('id'))
        require(isinstance(account.get('email'), str) and '@' in account['email']
                and len(account['email']) <= 320, 'synthetic_account_email')
        require(isinstance(account.get('password'), str) and 8 <= len(account['password']) <= 1024,
                'synthetic_account_password')
        # Deliberately discard saved tokens in memory; leave the original receipt untouched.
        result[account['role']] = {k: account[k] for k in ('id', 'email', 'password')}
    require(result['primary']['id'] != result['foreign']['id']
            and result['primary']['email'].casefold() != result['foreign']['email'].casefold(),
            'synthetic_accounts_distinct')
    return result


def auth_config(config):
    origin = config.get('SUPABASE_URL', '').rstrip('/')
    parsed = urlsplit(origin)
    require(parsed.scheme == 'https' and re.fullmatch(r'[a-z0-9-]+\.supabase\.co', parsed.netloc)
            and not parsed.path and not parsed.query and not parsed.fragment, 'auth_origin')
    key = config.get('SUPABASE_PUBLISHABLE_KEY')
    require(isinstance(key, str) and 20 <= len(key) <= 8192, 'auth_configuration')
    return origin, key


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'journal_directory_permissions')


@contextmanager
def exclusive_run(directory):
    private_directory(directory)
    descriptor = os.open(directory / '.run.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600, 'journal_lock_permissions')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SmokeFailure('another_smoke_is_running') from None
        yield
    finally:
        os.close(descriptor)


class Journal:
    def __init__(self, directory, accounts, sha):
        private_directory(directory)
        self.run_id = str(uuid4())
        self.path = directory / f'{self.run_id}.json'
        self.data = {'version': 1, 'tag': TAG, 'run_id': self.run_id, 'started_at': utc_now(),
                     'expected_sha': sha, 'status': 'running', 'checks': [], 'operations': [],
                     'accounts': {role: {'id': row['id']} for role, row in accounts.items()},
                     'resources': {}, 'cleanup': {'accounts': 'retained', 'drafts_and_photos': 'retained',
                         'reason': 'No public draft deletion API; exact owned IDs retained for later authorized cleanup.'}}
        self.save()

    def save(self):
        descriptor, temporary = tempfile.mkstemp(prefix='.smoke-', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(self.data, stream, separators=(',', ':'), sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def check(self, condition, name):
        require(condition, name)
        self.data['checks'].append(name)
        self.save()

    def begin(self, name, role):
        operation = {'id': str(uuid4()), 'name': name, 'role': role,
                     'state': 'intent_recorded', 'at': utc_now()}
        self.data['operations'].append(operation)
        self.save()  # Every mutation intent is durable before network I/O.
        return operation


class Smoke:
    def __init__(self, accounts, journal, api, auth, expected_sha):
        self.accounts, self.journal, self.api, self.auth = accounts, journal, api, auth
        self.expected_sha = expected_sha
        self.tokens = {}
        self.calls = 0
        self.deadline = time.monotonic() + 300

    def bounded(self, client, method, path, **kwargs):
        self.calls += 1
        require(self.calls <= 64 and time.monotonic() < self.deadline, 'network_budget')
        limit = 1024 * 1024
        headers = kwargs.pop('headers', {})
        headers['Accept-Encoding'] = 'identity'
        remaining = self.deadline - time.monotonic()
        with client.stream(method, path, headers=headers,
                           timeout=httpx.Timeout(min(remaining, 60 if path == '/v1/discovery' else 20), connect=min(remaining, 5)),
                           **kwargs) as response:
            require(response.headers.get('content-encoding', 'identity') == 'identity', 'unexpected_response_encoding')
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                require(size <= limit and time.monotonic() < self.deadline, 'response_budget')
                chunks.append(chunk)
            return response.status_code, response.headers, b''.join(chunks)

    def call(self, name, method, path, role=None, expected=200, raw=False, **kwargs):
        require(any(re.fullmatch(pattern, path) for pattern in ALLOWED.get(method, [])), 'endpoint_not_allowed')
        # This sole guided-upload probe must target the other account's new
        # draft and expect denial. A successful own guided upload calls framing.
        if method == 'POST' and path.endswith('/capture/photos'):
            primary = self.journal.data['resources'].get('primary', {})
            require(role == 'foreign' and expected == 404
                    and path == f'/v1/estimates/{primary.get("estimate_id")}/capture/photos', 'guided_probe_scope')
        headers = {'Authorization': 'Bearer ' + self.tokens[role]} if role else {}
        operation = self.journal.begin(name, role) if method != 'GET' else None
        try:
            code, response_headers, data = self.bounded(self.api, method, path, headers=headers, **kwargs)
        except Exception:
            if operation:
                operation['state'] = 'unknown_no_automatic_retry'
                self.journal.save()
            raise
        if operation:
            # Even a 500 can follow a committed mutation. Never treat it as rejection.
            operation.update(http_status=code, state='response_received' if code == expected else 'unexpected_no_retry')
            self.journal.save()
        self.journal.check(code == expected, name + '_http')
        if path.startswith('/v1/'):
            require('no-store' in response_headers.get('cache-control', ''), 'private_cache_policy')
        if expected >= 400:
            return None  # Never preserve or print provider error bodies.
        value = data if raw else json.loads(data)
        # Capture returned identifiers in the same operation receipt immediately,
        # including if a later resource-shape assertion fails.
        if operation and isinstance(value, dict) and isinstance(value.get('id'), str):
            operation['resource_id'] = identifier(value['id'])
            self.journal.save()
        return value

    def sign_in(self, role):
        account = self.accounts[role]
        code, _, raw = self.bounded(self.auth, 'POST', '/auth/v1/token?grant_type=password',
                                   json={'email': account['email'], 'password': account['password']})
        require(code == 200, 'normal_sign_in')
        data = json.loads(raw)
        user = data.get('user', {})
        self.journal.check(user.get('id') == account['id']
                           and str(user.get('email', '')).casefold() == account['email'].casefold()
                           and not user.get('is_anonymous', False), role + '_auth_identity')
        token = data.get('access_token')
        require(isinstance(token, str) and 1 <= len(token) <= 16384, 'normal_sign_in_token')
        self.tokens[role] = token

    def run(self):
        j = self.journal
        version = self.call('release_version', 'GET', '/version')
        j.check(version.get('source_sha') == self.expected_sha, 'expected_deployed_revision')
        ready = self.call('release_readiness', 'GET', '/ready')
        j.check(ready.get('status') == 'ready', 'database_and_volume_ready')
        j.data['schema_revision'] = ready.get('schema_revision')
        j.save()
        resources, before = j.data['resources'], {}
        for role in ('primary', 'foreign'):
            self.sign_in(role)
            bootstrap = self.call(role + '_bootstrap', 'GET', '/v1/bootstrap', role)
            j.check(bootstrap['profile']['id'] == self.accounts[role]['id']
                    and bootstrap['capabilities']['demo'] is False, role + '_real_customer_scope')
            j.check(sum(v.get('nickname', '').startswith(MARKER) for v in bootstrap['vehicles']) < 5,
                    role + '_fixture_quota')
            before[role] = {r['id'] for r in bootstrap['requests']}
        # Both authenticated identities are verified before either receives test resources.
        for role in ('primary', 'foreign'):
            marker = MARKER + j.run_id + ' ' + role
            row = self.call(role + '_create_vehicle', 'POST', '/v1/vehicles', role, expected=201,
                            json={'year': 2021, 'make': 'Toyota', 'model': 'Tacoma', 'nickname': marker, 'vin': ''})
            resources[role] = {'vehicle_id': identifier(row['id']), 'marker': marker}
            j.save()
            draft = self.call(role + '_create_draft', 'POST', '/v1/estimates', role, expected=201,
                              json={'vehicle_id': row['id'], 'discipline': 'pdr', 'description': marker})
            resources[role]['estimate_id'] = identifier(draft['id'])
            j.save()
            j.check(draft['status'] == 'draft' and draft.get('provider_id') is None, role + '_private_draft_only')

        primary, foreign = resources['primary'], resources['foreign']
        self.call('foreign_vehicle_draft_creation', 'POST', '/v1/estimates', 'foreign', expected=404,
                  json={'vehicle_id': primary['vehicle_id'], 'discipline': 'pdr',
                        'description': MARKER + j.run_id + ' foreign-ownership-probe'})
        query = {'postal_code': '80204', 'radius_miles': 30, 'vehicle_id': primary['vehicle_id'],
                 'specialty': 'pdr', 'mobile_only': 'true'}
        result = self.call('nearby_mobile_directory', 'GET', '/v1/discovery', 'primary', params=query)
        listings = result['providers'] + result['shop_visit_alternatives']
        j.check(len(listings) <= 100, 'directory_combined_cap_100')
        j.check(result['exhaustive'] is False and result['radius_miles'] == 30
                and result['distance_basis'] == 'zip_centroid' and isinstance(result['truncated'], bool),
                'directory_distance_and_coverage_labels')
        j.check(result['status'] in ('ready', 'stale', 'unavailable') and bool(result['source_attributions']),
                'directory_availability_and_attribution')
        demolition = [p for p in result['shop_visit_alternatives']
                      if p['source'] == 'estimoto' and p['source_id'] == DEMOLITION_SOURCE]
        j.check(len(demolition) == 1 and 'shop_visit' in demolition[0]['request_modes']
                and 'mobile' not in demolition[0]['request_modes'] and demolition[0]['distance_miles'] <= 30,
                'demolition_shop_visit_fallback')
        j.data['directory'] = {'status': result['status'], 'returned': len(listings),
                               'truncated': result['truncated'], 'demolition_source_id': DEMOLITION_SOURCE}
        j.save()
        favorite = {'vehicle_id': primary['vehicle_id'], 'source': 'estimoto', 'source_id': DEMOLITION_SOURCE}
        saved = self.call('save_private_favorite', 'PUT', '/v1/discovery/favorites/pdr', 'primary', json=favorite)
        j.data['cleanup']['favorite'] = {'state': 'retained_until_verified_cleanup', **favorite}
        j.save()
        replay = self.call('replay_private_favorite', 'PUT', '/v1/discovery/favorites/pdr', 'primary', json=favorite)
        j.check(saved == replay == {**favorite, 'specialty': 'pdr'}, 'favorite_idempotent_replay')
        rows = self.call('owned_favorite_read', 'GET', '/v1/discovery/favorites', 'primary',
                         params={'vehicle_id': primary['vehicle_id']})
        j.check(rows == [saved], 'favorite_owned_read')
        for method in ('GET', 'PUT', 'DELETE'):
            path = '/v1/discovery/favorites' + ('' if method == 'GET' else '/pdr')
            kwargs = {'json': favorite} if method == 'PUT' else {'params': {'vehicle_id': primary['vehicle_id']}}
            self.call('foreign_favorite_' + method.lower(), method, path, 'foreign', expected=404, **kwargs)
        rows = self.call('foreign_own_favorites', 'GET', '/v1/discovery/favorites', 'foreign',
                         params={'vehicle_id': foreign['vehicle_id']})
        j.check(rows == [], 'favorites_do_not_cross_customer')
        self.call('foreign_directory_vehicle', 'GET', '/v1/discovery', 'foreign', expected=404, params=query)

        estimate = primary['estimate_id']
        capture = f'/v1/estimates/{estimate}/capture'
        self.call('anonymous_capture_state', 'GET', capture, expected=401)
        self.call('foreign_capture_state', 'GET', capture, 'foreign', expected=404)
        state = self.call('owned_empty_capture_state', 'GET', capture, 'primary')
        j.check(state['estimate_id'] == estimate and state['photos'] == []
                and state['vehicle']['vin'] == '', 'owned_empty_capture')
        image = BytesIO()
        Image.new('RGB', (80, 80), (190, 210, 230)).save(image, 'JPEG')
        jpeg = image.getvalue()
        digest = hashlib.sha256(jpeg).hexdigest()
        operation = str(uuid4())
        primary['foreign_capture_operation_id'] = operation
        primary['synthetic_photo_sha256'] = digest
        j.save()
        self.call('foreign_guided_upload', 'POST', capture + '/photos', 'foreign', expected=404,
                  files={'photo': ('synthetic.jpg', jpeg, 'image/jpeg')},
                  data={'capture_key': 'vin', 'body_style': 'truck', 'operation_id': operation})
        # Reviewed legacy route shares durable private storage but intentionally
        # does not call framing/OCR. Root's separate UI proof covers those calls.
        photo = self.call('synthetic_private_vin_upload', 'POST', f'/v1/estimates/{estimate}/photos', 'primary', expected=201,
                          files={'file': ('synthetic.jpg', jpeg, 'image/jpeg')}, data={'label': 'vin'})
        primary['photo_id'] = identifier(photo['id'])
        j.save()
        state = self.call('owned_capture_state', 'GET', capture, 'primary')
        j.check(state['photos'] == [{'id': photo['id'], 'label': 'vin', 'sha256': digest, 'quality': 'not_checked'}]
                and state['vin_suggestion'] is None and state['vehicle']['vin'] == '', 'photo_receipt_and_no_automatic_vin')
        photo_path = f'/v1/estimates/{estimate}/photos/{photo["id"]}'
        stored = self.call('owned_photo_bytes', 'GET', photo_path, 'primary', raw=True)
        j.check(stored == jpeg, 'private_photo_bytes_unchanged')
        self.call('foreign_photo_bytes', 'GET', photo_path, 'foreign', expected=404)
        self.call('anonymous_photo_bytes', 'GET', photo_path, expected=401)
        self.call('foreign_estimate_photo_reference', 'GET',
                  f'/v1/estimates/{foreign["estimate_id"]}/photos/{photo["id"]}', 'foreign', expected=404)
        confirm = {'photo_id': photo['id'], 'photo_sha256': digest, 'expected_vin': '', 'vin': SYNTHETIC_VIN}
        self.call('foreign_vin_confirmation', 'POST', capture + '/vin/confirm', 'foreign', expected=404, json=confirm)
        self.call('foreign_owned_draft_vin_photo_reference', 'POST',
                  f'/v1/estimates/{foreign["estimate_id"]}/capture/vin/confirm', 'foreign', expected=404, json=confirm)
        self.call('invalid_vin_confirmation', 'POST', capture + '/vin/confirm', 'primary', expected=422,
                  json={**confirm, 'vin': 'I' * 17})
        self.call('changed_photo_vin_confirmation', 'POST', capture + '/vin/confirm', 'primary', expected=409,
                  json={**confirm, 'photo_sha256': '0' * 64})
        for name in ('explicit_synthetic_vin_confirmation', 'same_vin_confirmation_replay'):
            result = self.call(name, 'POST', capture + '/vin/confirm', 'primary', json=confirm)
            j.check(result == {'vin': SYNTHETIC_VIN, 'confirmed': True}, name + '_saved')
        self.call('stale_vin_compare_and_set', 'POST', capture + '/vin/confirm', 'primary', expected=409,
                  json={**confirm, 'vin': '1HGCM82633A004353'})
        for role in ('primary', 'foreign'):
            state = self.call(role + '_final_capture', 'GET', f'/v1/estimates/{resources[role]["estimate_id"]}/capture', role)
            j.check(state['vehicle']['vin'] == (SYNTHETIC_VIN if role == 'primary' else ''), role + '_final_vin_scope')
            bootstrap = self.call(role + '_final_bootstrap', 'GET', '/v1/bootstrap', role)
            j.check({r['id'] for r in bootstrap['requests']} == before[role], role + '_no_new_service_requests')
            drafts = [e for e in bootstrap['estimates'] if e['id'] == resources[role]['estimate_id']]
            j.check(len(drafts) == 1 and drafts[0]['status'] == 'draft' and drafts[0].get('provider_id') is None,
                    role + '_not_submitted')
        # Delete only this run's exact favorite on its newly created vehicle.
        rows = self.call('favorite_cleanup_precondition', 'GET', '/v1/discovery/favorites', 'primary',
                         params={'vehicle_id': primary['vehicle_id']})
        j.check(rows == [saved], 'favorite_cleanup_exact_reference')
        self.call('favorite_cleanup', 'DELETE', '/v1/discovery/favorites/pdr', 'primary',
                  params={'vehicle_id': primary['vehicle_id']})
        rows = self.call('favorite_cleanup_readback', 'GET', '/v1/discovery/favorites', 'primary',
                         params={'vehicle_id': primary['vehicle_id']})
        j.check(rows == [], 'favorite_cleanup_verified')
        j.data['cleanup']['favorite']['state'] = 'removed_verified'
        j.data.update(status='passed', finished_at=utc_now(), http_calls=self.calls)
        j.save()


def self_test():
    """Real local FastAPI/SQLite routes, fake Auth/OSM, socket connections denied."""
    import socket
    import unittest
    from unittest.mock import patch
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select, text
    from estimoto_plus.app import create_app
    from estimoto_plus.config import Settings
    from estimoto_plus.models import EstimateOutbox, Outbox, Provider, ServiceRequest
    from estimoto_plus.shop_models import ShopOutbox, ShopOutreach

    class Tests(unittest.TestCase):
        def setUp(self):
            self.tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self.tmp.cleanup)
            self.directory = Path(self.tmp.name)
            self.receipt = {'tag': TAG, 'accounts': [
                {'role': role, 'id': str(uuid4()), 'email': role + '@example.test', 'password': 'synthetic-password'}
                for role in ('primary', 'foreign')]}
            self.accounts = validate_accounts(self.receipt)
            self.journal = Journal(self.directory / 'receipts', self.accounts, 'a' * 40)

        def test_receipt_boundaries(self):
            for bad in ({**self.receipt, 'tag': 'unrelated'}, {**self.receipt, 'accounts': self.receipt['accounts'][:1]},
                        {**self.receipt, 'accounts': [self.receipt['accounts'][0]] * 2}):
                with self.assertRaises(SmokeFailure):
                    validate_accounts(bad)
            private = self.directory / 'input.json'
            private.write_text(json.dumps(self.receipt))
            private.chmod(0o644)
            with self.assertRaises(SmokeFailure):
                read_private_json(private)
            private.chmod(0o600)
            self.assertEqual(read_private_json(private), self.receipt)
            link = self.directory / 'link.json'
            link.symlink_to(private)
            with self.assertRaises(OSError):
                read_private_json(link)
            with exclusive_run(self.directory / 'locks'):
                with self.assertRaises(SmokeFailure):
                    with exclusive_run(self.directory / 'locks'):
                        pass

        def test_auth_origin_boundary(self):
            for url in ('http://example.supabase.co', 'https://evil.test', 'https://a.supabase.co@evil.test',
                        'https://a.supabase.co/path', 'https://a.supabase.co?key=secret'):
                with self.assertRaises(SmokeFailure):
                    auth_config({'SUPABASE_URL': url, 'SUPABASE_PUBLISHABLE_KEY': 'a' * 40})

        def test_network_and_send_guards(self):
            calls = []
            def timeout(request):
                calls.append(request)
                raise httpx.ReadTimeout('secret-body-do-not-report')
            with httpx.Client(transport=httpx.MockTransport(timeout), base_url=API_ORIGIN) as client:
                smoke = Smoke(self.accounts, self.journal, client, client, 'a' * 40)
                smoke.tokens['primary'] = 'synthetic'
                for path in ('/v1/requests', '/v1/estimates/' + str(uuid4()) + '/submit',
                             '/v1/my-shops', '/v1/calendar/google/connect', '/auth/v1/admin/users',
                             '/v1/estimates/' + str(uuid4()) + '/capture/guidance'):
                    with self.assertRaises(SmokeFailure):
                        smoke.call('forbidden', 'POST', path, 'primary')
                self.assertEqual(calls, [])
                with self.assertRaises(httpx.ReadTimeout):
                    smoke.call('synthetic_create', 'POST', '/v1/vehicles', 'primary', json={})
                self.assertEqual(len(calls), 1)
                record = read_private_json(self.journal.path)
                self.assertEqual(record['operations'][-1]['state'], 'unknown_no_automatic_retry')
                self.assertNotIn('secret-body', self.journal.path.read_text())

        def test_wrong_identity_aborts_before_mutation(self):
            def wrong(_):
                return httpx.Response(200, json={'user': {'id': str(uuid4()), 'email': 'someone@example.test'},
                                                'access_token': 'never-save-me'})
            with httpx.Client(transport=httpx.MockTransport(wrong), base_url='https://synthetic.supabase.co') as client:
                smoke = Smoke(self.accounts, self.journal, client, client, 'a' * 40)
                with self.assertRaises(SmokeFailure):
                    smoke.sign_in('primary')
                self.assertEqual(smoke.tokens, {})
                self.assertEqual(self.journal.data['operations'], [])
                self.assertNotIn('never-save-me', self.journal.path.read_text())

        def test_release_mismatch_stops_before_login(self):
            calls = []
            def version(request):
                calls.append(request.url.path)
                return httpx.Response(200, json={'source_sha': 'b' * 40})
            with httpx.Client(transport=httpx.MockTransport(version), base_url=API_ORIGIN) as client:
                smoke = Smoke(self.accounts, self.journal, client, client, 'a' * 40)
                with self.assertRaises(SmokeFailure):
                    smoke.run()
                self.assertEqual(calls, ['/version'])
                self.assertEqual(self.journal.data['operations'], [])

        def test_response_bound_and_no_compression(self):
            for response in (httpx.Response(200, content=b'x' * (1024 * 1024 + 1)),
                             httpx.Response(200, headers={'Content-Encoding': 'unexpected'}, content=b'{}')):
                with httpx.Client(transport=httpx.MockTransport(lambda _: response), base_url=API_ORIGIN) as client:
                    smoke = Smoke(self.accounts, self.journal, client, client, 'a' * 40)
                    with self.assertRaises(SmokeFailure):
                        smoke.call('bounded_read', 'GET', '/version')

        def test_real_api_workflow_and_zero_outboxes(self):
            settings = Settings(database_url=f'sqlite:///{self.directory}/test.db', environment='test',
                worker_enabled=False, photo_dir=str(self.directory / 'photos'), source_sha='a' * 40,
                discovery_enabled=True, bridge_key='', bridge_url='', estimate_bridge_url='',
                carsxe_api_key='', calendar_enabled=False, nango_api_key='')
            identities = {a['id']: {'id': a['id'], 'email': a['email'], 'confirmed_at': 'ok'} for a in self.accounts.values()}
            app = create_app(settings, auth_verifier=lambda token: identities.get(token))
            self.addCleanup(app.state.engine.dispose)
            Path(settings.photo_dir).mkdir()
            with app.state.engine.begin() as db:
                db.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'))
                db.execute(text("INSERT INTO alembic_version VALUES ('32ac7f618b90')"))
            with app.state.session_factory() as db:
                db.add(Provider(source_id=DEMOLITION_SOURCE, name='Synthetic participating shop', kind='shop',
                    specialties=['pdr'], postal_codes=['80221'], address='1 Synthetic Street, Denver CO 80221',
                    public_visible=True, accepting_requests=True, mobile_service=False))
                db.commit()
            def public(request):
                if request.url.host == 'api.zippopotam.us':
                    postal = request.url.path.split('/')[-1]
                    return httpx.Response(200, json={'post code': postal, 'country abbreviation': 'US', 'places': [
                        {'latitude': '39.82' if postal == '80221' else '39.734', 'longitude': '-105.0259',
                         'place name': 'Synthetic', 'state abbreviation': 'CO'}]})
                self.assertEqual(request.url.host, 'overpass-api.de')
                return httpx.Response(200, json={'elements': [
                    {'type': 'node', 'id': i, 'lat': 39.74, 'lon': -105.0259,
                         'tags': {'shop': 'car_repair', 'name': f'Synthetic repair {i}'}} for i in range(1, 131)]})
            app.state.discovery_transport = httpx.MockTransport(public)
            def never_provider(_):
                self.fail('No capture, bridge, calendar or mail provider call is permitted')
            app.state.capture_transport = app.state.bridge_transport = app.state.calendar_transport = httpx.MockTransport(never_provider)
            app.state.shop_mail_transport = httpx.MockTransport(never_provider)
            def authenticate(request):
                self.assertEqual(request.url.path, '/auth/v1/token')
                self.assertEqual(request.url.query, b'grant_type=password')
                body = json.loads(request.content)
                account = next(a for a in self.accounts.values() if a['email'] == body['email'])
                self.assertEqual(body['password'], account['password'])
                return httpx.Response(200, json={'user': identities[account['id']], 'access_token': account['id']})
            with patch.object(socket.socket, 'connect', side_effect=AssertionError('External sockets forbidden')):
                with TestClient(app) as local:
                    def forward(request):
                        result = local.request(request.method, str(request.url).removeprefix(API_ORIGIN),
                                               content=request.content, headers=dict(request.headers))
                        return httpx.Response(result.status_code, content=result.content, headers=result.headers)
                    with httpx.Client(base_url=API_ORIGIN, transport=httpx.MockTransport(forward)) as api, \
                         httpx.Client(base_url='https://synthetic.supabase.co', transport=httpx.MockTransport(authenticate)) as auth:
                        smoke = Smoke(self.accounts, self.journal, api, auth, 'a' * 40)
                        smoke.run()
            self.assertEqual(self.journal.data['status'], 'passed')
            self.assertEqual(self.journal.data['directory']['returned'], 100)
            self.assertTrue(self.journal.data['directory']['truncated'])
            self.assertEqual(self.journal.data['cleanup']['favorite']['state'], 'removed_verified')
            self.assertEqual(stat.S_IMODE(self.journal.path.stat().st_mode), 0o600)
            with app.state.session_factory() as db:
                for model in (ServiceRequest, Outbox, EstimateOutbox, ShopOutbox, ShopOutreach):
                    self.assertEqual(db.scalar(select(func.count()).select_from(model)), 0)
            print(json.dumps({'local_api_checks': len(self.journal.data['checks']), 'local_http_calls': smoke.calls,
                              'synthetic_listings': 130, 'returned_listings': 100, 'outbox_rows': 0,
                              'external_socket_connections': 0}))

    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    return 0 if result.wasSuccessful() else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--run-live', action='store_true', help='Only after explicit release-owner authorization')
    modes.add_argument('--self-test', action='store_true', help='Synthetic isolated local API proof; no protected input or network')
    parser.add_argument('--expected-sha', help='Required deployed full source revision for live mode')
    args = parser.parse_args()
    # Do not allow ambient HTTP debugging to print sign-in payloads or credentials.
    logging.disable(logging.CRITICAL)
    if args.self_test:
        return self_test()
    accounts = validate_accounts(read_private_json(ACCOUNT_FILE))
    origin, key = auth_config(read_private_json(CONFIG_FILE))
    if not args.run_live:
        print(json.dumps({'status': 'dry_inputs_valid', 'network_calls': 0, 'synthetic_accounts': 2,
                          'live_authorization_required': True}))
        return 0
    require(isinstance(args.expected_sha, str) and re.fullmatch(r'[a-f0-9]{40}', args.expected_sha), 'expected_sha_required')
    with exclusive_run(QA_DIR / 'guided-smoke'):
        journal = Journal(QA_DIR / 'guided-smoke', accounts, args.expected_sha)
        try:
            with httpx.Client(base_url=API_ORIGIN, follow_redirects=False, trust_env=False) as api, \
                 httpx.Client(base_url=origin, headers={'apikey': key}, follow_redirects=False, trust_env=False) as auth:
                Smoke(accounts, journal, api, auth, args.expected_sha).run()
        except Exception as exc:
            journal.data.update(status='failed_inspect_protected_receipt', finished_at=utc_now())
            # SmokeFailure contains only local check labels. All other failures
            # are collapsed to a fixed category; never serialize str(exc).
            if isinstance(exc, SmokeFailure) and re.fullmatch(r'[a-z0-9_]{1,100}', str(exc)):
                journal.data['failed_check'] = str(exc)
            else:
                journal.data['failed_check'] = 'transport_or_input_failure'
            journal.save()
            raise
        print(json.dumps({'status': 'passed', 'checks': len(journal.data['checks']),
                          'http_calls': journal.data['http_calls'], 'source_sha': args.expected_sha,
                          'directory_status': journal.data['directory']['status'],
                          'protected_receipts': '~/.config/estimoto-plus/qa/guided-smoke/'}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        # Never print str(exc), traceback, response bodies, URLs or auth data.
        print('Guided smoke stopped. Inspect the protected receipt and local input permissions; no automatic retry was made.', file=sys.stderr)
        raise SystemExit(2)
