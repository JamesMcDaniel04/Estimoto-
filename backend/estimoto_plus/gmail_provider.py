"""Fixed Nango protocol adapter for read-only Gmail. Tokens and provider error bodies never escape it."""
import hashlib
import json
import re
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import quote, urlparse

import httpx

BASE = "https://api.nango.dev"
INTEGRATION = "estimoto-plus-gmail"
SCOPES = frozenset({"https://www.googleapis.com/auth/gmail.readonly"})
MAX_RESPONSE = 1024 * 1024
MAX_MESSAGES = 25
MESSAGE_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
# Only car-service mail from the last quarter, and only what the customer asked to scan for.
SCAN_QUERY = ('newer_than:90d -category:promotions -category:social '
              'subject:(estimate OR quote OR invoice OR receipt OR appointment OR service OR repair OR maintenance '
              'OR "oil change" OR collision OR dent OR "body shop" OR tire OR tires OR brake OR brakes OR inspection)')
CATEGORY_RULES = (
    ('receipt', re.compile(r'\b(receipt|invoice|paid|payment|thank you for your (purchase|business))\b', re.I)),
    ('estimate', re.compile(r'\b(estimate|quote|quotation)\b', re.I)),
    ('appointment', re.compile(r'\b(appointment|scheduled|booking|confirmed|reminder|drop[- ]?off|pick[- ]?up)\b', re.I)),
)


class GmailUnavailable(Exception):
    def __init__(self, status=503):
        super().__init__("Mail provider is unavailable.")
        self.status = status


def configured(settings):
    fingerprints = {v.strip() for v in settings.nango_allowed_key_fingerprints.split(',') if v.strip()}
    return bool(settings.gmail_enabled and settings.nango_api_key and
                settings.nango_environment == 'production' and settings.nango_gmail_integration_id == INTEGRATION and
                hashlib.sha256(settings.nango_api_key.encode()).hexdigest() in fingerprints)


def instant(value):
    if not isinstance(value, str) or len(value) > 50:
        raise GmailUnavailable()
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise GmailUnavailable() from None


def tags(customer_id, attempt_id, environment):
    return {'customer_id': customer_id, 'app': 'estimoto-plus', 'attempt_id': attempt_id, 'environment': environment}


def connection_id(data):
    value = data.get('connection_id') or data.get('connectionId')
    return value if isinstance(value, str) and 0 < len(value) <= 200 else None


def owned(data, customer_id, attempt_id, settings, *, require_usable=True):
    if not isinstance(data, dict) or require_usable and data.get('errors'):
        return False
    if (data.get('provider_config_key') or data.get('providerConfigKey')) != settings.nango_gmail_integration_id:
        return False
    expected = tags(customer_id, attempt_id, settings.nango_environment)
    if not isinstance(data.get('tags'), dict) or any(data['tags'].get(k) != v for k, v in expected.items()):
        return False
    scopes = data.get('granted_scopes', data.get('scopes'))
    if require_usable and scopes is not None:
        if isinstance(scopes, str):
            scopes = scopes.replace(',', ' ').split()
        if not isinstance(scopes, list) or not SCOPES.issubset(set(v for v in scopes if isinstance(v, str))):
            return False
    return connection_id(data) is not None


def clean(value, limit):
    if not isinstance(value, str):
        return ''
    return ' '.join(value.split())[:limit]


def categorize(subject, snippet=''):
    text = f'{subject} {snippet}'
    for name, pattern in CATEGORY_RULES:
        if pattern.search(text):
            return name
    return 'service'


class GmailProvider:
    def __init__(self, settings, transport=None):
        if not configured(settings):
            raise GmailUnavailable()
        self.settings, self.transport = settings, transport

    def call(self, method, path, *, connection=None, params=None, body=None, allow=()):
        if not path.startswith(('/connect/sessions', '/connections', '/proxy/gmail/v1/users/me/')) or '?' in path or '#' in path:
            raise GmailUnavailable()
        headers = {'Authorization': f'Bearer {self.settings.nango_api_key}', 'Retries': '0'}
        if connection is not None:
            headers.update({'Provider-Config-Key': self.settings.nango_gmail_integration_id, 'Connection-Id': connection})
        try:
            with httpx.Client(timeout=httpx.Timeout(15, connect=5), transport=self.transport, follow_redirects=False) as client:
                with client.stream(method, BASE + path, headers=headers, params=params, json=body) as response:
                    if response.status_code in allow:
                        return response.status_code, None
                    if not 200 <= response.status_code < 300:
                        raise GmailUnavailable(response.status_code)
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_RESPONSE:
                            raise GmailUnavailable()
                    if response.status_code == 204:
                        return response.status_code, {}
                    value = json.loads(data)
                    if not isinstance(value, dict):
                        raise GmailUnavailable()
                    return response.status_code, value
        except (httpx.HTTPError, ValueError, TypeError):
            raise GmailUnavailable() from None

    def connect(self, customer_id, attempt_id):
        _, payload = self.call('POST', '/connect/sessions', body={
            'allowed_integrations': [self.settings.nango_gmail_integration_id],
            'tags': tags(customer_id, attempt_id, self.settings.nango_environment)})
        data = payload.get('data', payload)
        if not isinstance(data, dict):
            raise GmailUnavailable()
        link = data.get('connect_link')
        if not isinstance(link, str) or len(link) > 4096:
            raise GmailUnavailable()
        url = urlparse(link)
        if url.scheme != 'https' or url.netloc != 'connect.nango.dev' or url.path not in ('', '/') or url.fragment:
            raise GmailUnavailable()
        return link, instant(data.get('expires_at'))

    def reconcile(self, customer_id, attempt_id, *, require_usable=True):
        _, data = self.call('GET', '/connections', params={
            **{f'tags[{k}]': v for k, v in tags(customer_id, attempt_id, self.settings.nango_environment).items()}, 'limit': 100})
        nested = data.get('data', data)
        rows = data.get('connections', nested.get('connections') if isinstance(nested, dict) else None)
        if not isinstance(rows, list) or len(rows) >= 100 or data.get('next_cursor') or data.get('nextCursor'):
            raise GmailUnavailable()
        matches = [row for row in rows if owned(row, customer_id, attempt_id, self.settings, require_usable=require_usable)]
        if len(matches) != 1:
            return None
        identifier = connection_id(matches[0])
        _, detail = self.call('GET', '/connections/' + quote(identifier, safe=''), params={'provider_config_key': self.settings.nango_gmail_integration_id})
        detail = detail.get('data', detail)
        return identifier if owned(detail, customer_id, attempt_id, self.settings, require_usable=require_usable) and connection_id(detail) == identifier else None

    def revoke(self, connection, customer_id, attempt_id):
        code, data = self.call('GET', '/connections/' + quote(connection, safe=''),
                               params={'provider_config_key': self.settings.nango_gmail_integration_id}, allow=(404,))
        if code == 404:
            return
        data = data.get('data', data)
        if not owned(data, customer_id, attempt_id, self.settings, require_usable=False) or connection_id(data) != connection:
            raise GmailUnavailable()
        self.call('DELETE', '/connections/' + quote(connection, safe=''),
                  params={'provider_config_key': self.settings.nango_gmail_integration_id}, allow=(404,))

    def verify_connection(self, connection, customer_id, attempt_id):
        code, data = self.call('GET', '/connections/' + quote(connection, safe=''),
                               params={'provider_config_key': self.settings.nango_gmail_integration_id}, allow=(404,))
        if code == 404:
            raise GmailUnavailable(401)
        data = data.get('data', data)
        if not owned(data, customer_id, attempt_id, self.settings) or connection_id(data) != connection:
            raise GmailUnavailable(403)

    def profile(self, connection):
        _, data = self.call('GET', '/proxy/gmail/v1/users/me/profile', connection=connection)
        address = data.get('emailAddress')
        if not isinstance(address, str) or not 3 <= len(address) <= 320 or '@' not in address or any(ord(c) < 33 for c in address):
            raise GmailUnavailable()
        return address

    def list_messages(self, connection):
        _, data = self.call('GET', '/proxy/gmail/v1/users/me/messages', connection=connection,
                            params={'q': SCAN_QUERY, 'maxResults': MAX_MESSAGES, 'includeSpamTrash': 'false'})
        rows = data.get('messages', [])
        if not isinstance(rows, list) or len(rows) > MAX_MESSAGES:
            raise GmailUnavailable()
        identifiers = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not MESSAGE_ID.fullmatch(row['id']):
                raise GmailUnavailable()
            if row['id'] not in identifiers:
                identifiers.append(row['id'])
        return identifiers

    def message(self, connection, identifier):
        if not MESSAGE_ID.fullmatch(identifier):
            raise GmailUnavailable()
        _, data = self.call('GET', '/proxy/gmail/v1/users/me/messages/' + identifier, connection=connection,
                            params={'format': 'metadata', 'metadataHeaders': ['From', 'Subject', 'Date']})
        if data.get('id') != identifier:
            raise GmailUnavailable()
        headers = {}
        payload = data.get('payload')
        for header in (payload.get('headers', []) if isinstance(payload, dict) else []):
            if isinstance(header, dict) and isinstance(header.get('name'), str) and isinstance(header.get('value'), str):
                headers.setdefault(header['name'].lower(), header['value'])
        name, address = parseaddr(clean(headers.get('from'), 500))
        received = None
        stamp = data.get('internalDate')
        if isinstance(stamp, str) and stamp.isdigit() and len(stamp) <= 16:
            received = datetime.fromtimestamp(int(stamp) / 1000, tz=timezone.utc)
        elif headers.get('date'):
            try:
                received = parsedate_to_datetime(headers['date'])
                received = received.astimezone(timezone.utc) if received.tzinfo else received.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                received = None
        if received is None:
            raise GmailUnavailable()
        thread = data.get('threadId')
        subject = clean(headers.get('subject'), 300)
        snippet = clean(data.get('snippet'), 300)
        return {'message_id': identifier, 'thread_id': thread if isinstance(thread, str) and MESSAGE_ID.fullmatch(thread) else '',
                'sender_name': clean(name, 200) or clean(address.split('@')[0], 200), 'sender_address': clean(address, 320),
                'subject': subject or '(no subject)', 'snippet': snippet, 'received_at': received,
                'category': categorize(subject, snippet)}
