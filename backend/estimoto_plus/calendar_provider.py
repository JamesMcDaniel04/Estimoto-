"""Fixed Nango protocol adapter. Tokens and provider error bodies never escape it."""
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

BASE = "https://api.nango.dev"
INTEGRATION = "estimoto-plus-google-calendar"
SCOPES = frozenset("https://www.googleapis.com/auth/" + suffix for suffix in (
    "calendar.calendarlist.readonly", "calendar.events.freebusy", "calendar.app.created"))
MAX_RESPONSE = 1024 * 1024


class CalendarUnavailable(Exception):
    def __init__(self, status=503):
        super().__init__("Calendar provider is unavailable.")
        self.status = status


def configured(settings):
    fingerprints = {v.strip() for v in settings.nango_allowed_key_fingerprints.split(',') if v.strip()}
    return bool(settings.calendar_enabled and settings.nango_api_key and
                settings.nango_environment == 'production' and settings.nango_calendar_integration_id == INTEGRATION and
                hashlib.sha256(settings.nango_api_key.encode()).hexdigest() in fingerprints)


def instant(value):
    if not isinstance(value, str) or len(value) > 50:
        raise CalendarUnavailable()
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc)
    except ValueError:
        raise CalendarUnavailable() from None


def tags(customer_id, attempt_id, environment):
    return {'customer_id': customer_id, 'app': 'estimoto-plus', 'attempt_id': attempt_id, 'environment': environment}


def connection_id(data):
    value = data.get('connection_id') or data.get('connectionId')
    return value if isinstance(value, str) and 0 < len(value) <= 200 else None


def owned(data, customer_id, attempt_id, settings, *, require_usable=True):
    if not isinstance(data, dict) or require_usable and data.get('errors'):
        return False
    if (data.get('provider_config_key') or data.get('providerConfigKey')) != settings.nango_calendar_integration_id:
        return False
    expected = tags(customer_id, attempt_id, settings.nango_environment)
    if not isinstance(data.get('tags'), dict) or any(data['tags'].get(k) != v for k, v in expected.items()):
        return False
    # Nango metadata does not always expose scopes. Never request credentials to inspect them.
    # When it does expose granted scopes, an incomplete grant is not a usable binding.
    scopes = data.get('granted_scopes', data.get('scopes'))
    if require_usable and scopes is not None:
        if isinstance(scopes, str):
            scopes = scopes.replace(',', ' ').split()
        if not isinstance(scopes, list) or not SCOPES.issubset(set(v for v in scopes if isinstance(v, str))):
            return False
    return connection_id(data) is not None


class CalendarProvider:
    def __init__(self, settings, transport=None):
        if not configured(settings):
            raise CalendarUnavailable()
        self.settings, self.transport = settings, transport

    def call(self, method, path, *, connection=None, params=None, body=None, allow=()):
        if not path.startswith(('/connect/sessions', '/connections', '/proxy/calendar/v3/')) or '?' in path or '#' in path:
            raise CalendarUnavailable()
        headers = {'Authorization': f'Bearer {self.settings.nango_api_key}', 'Retries': '0'}
        if connection is not None:
            headers.update({'Provider-Config-Key': self.settings.nango_calendar_integration_id, 'Connection-Id': connection})
        try:
            with httpx.Client(timeout=httpx.Timeout(15, connect=5), transport=self.transport, follow_redirects=False) as client:
                with client.stream(method, BASE + path, headers=headers, params=params, json=body) as response:
                    if response.status_code in allow:
                        return response.status_code, None
                    if not 200 <= response.status_code < 300:
                        raise CalendarUnavailable(response.status_code)
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_RESPONSE:
                            raise CalendarUnavailable()
                    if response.status_code == 204:
                        return response.status_code, {}
                    value = json.loads(data)
                    if not isinstance(value, dict):
                        raise CalendarUnavailable()
                    return response.status_code, value
        except (httpx.HTTPError, ValueError, TypeError):
            raise CalendarUnavailable() from None

    def connect(self, customer_id, attempt_id):
        _, payload = self.call('POST', '/connect/sessions', body={
            'allowed_integrations': [self.settings.nango_calendar_integration_id],
            'tags': tags(customer_id, attempt_id, self.settings.nango_environment)})
        data = payload.get('data', payload)
        if not isinstance(data, dict):
            raise CalendarUnavailable()
        link = data.get('connect_link')
        if not isinstance(link, str) or len(link) > 4096:
            raise CalendarUnavailable()
        url = urlparse(link)
        if url.scheme != 'https' or url.netloc != 'connect.nango.dev' or url.path not in ('', '/') or url.fragment:
            raise CalendarUnavailable()
        return link, instant(data.get('expires_at'))

    def reconcile(self, customer_id, attempt_id, *, require_usable=True):
        _, data = self.call('GET', '/connections', params={
            **{f'tags[{k}]': v for k, v in tags(customer_id, attempt_id, self.settings.nango_environment).items()}, 'limit': 100})
        nested = data.get('data', data)
        rows = data.get('connections', nested.get('connections') if isinstance(nested, dict) else None)
        if not isinstance(rows, list) or len(rows) >= 100 or data.get('next_cursor') or data.get('nextCursor'):
            raise CalendarUnavailable()
        matches = [row for row in rows if owned(row, customer_id, attempt_id, self.settings, require_usable=require_usable)]
        if len(matches) != 1:
            return None
        identifier = connection_id(matches[0])
        _, detail = self.call('GET', '/connections/' + quote(identifier, safe=''), params={'provider_config_key': self.settings.nango_calendar_integration_id})
        detail = detail.get('data', detail)
        return identifier if owned(detail, customer_id, attempt_id, self.settings, require_usable=require_usable) and connection_id(detail) == identifier else None

    def revoke(self, connection, customer_id, attempt_id):
        code, data = self.call('GET', '/connections/' + quote(connection, safe=''),
                               params={'provider_config_key': self.settings.nango_calendar_integration_id}, allow=(404,))
        if code == 404:
            return
        data = data.get('data', data)
        if not owned(data, customer_id, attempt_id, self.settings, require_usable=False) or connection_id(data) != connection:
            raise CalendarUnavailable()
        self.call('DELETE', '/connections/' + quote(connection, safe=''),
                  params={'provider_config_key': self.settings.nango_calendar_integration_id}, allow=(404,))

    def calendars(self, connection):
        rows, page, seen = [], None, set()
        for _ in range(5):
            _, data = self.call('GET', '/proxy/calendar/v3/users/me/calendarList', connection=connection,
                                params={'maxResults': 100, **({'pageToken': page} if page else {})})
            items = data.get('items', [])
            if not isinstance(items, list) or len(items) > 100:
                raise CalendarUnavailable()
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not 0 < len(item['id']) <= 500:
                    raise CalendarUnavailable()
                if item['id'] in seen:
                    raise CalendarUnavailable()
                seen.add(item['id'])
                if item.get('deleted') or item.get('accessRole') not in ('owner', 'writer', 'reader', 'freeBusyReader'):
                    continue
                if not isinstance(item.get('summary', ''), str) or not isinstance(item.get('timeZone', 'UTC'), str):
                    raise CalendarUnavailable()
                rows.append({k: item.get(k) for k in ('id', 'summary', 'primary', 'timeZone', 'accessRole', 'description')})
            next_page = data.get('nextPageToken')
            if not next_page:
                return rows
            if not isinstance(next_page, str) or len(next_page) > 2000 or next_page == page:
                raise CalendarUnavailable()
            page = next_page
        raise CalendarUnavailable()

    def freebusy(self, connection, selected, start, end):
        if not 1 <= len(selected) <= 10:
            raise CalendarUnavailable()
        _, data = self.call('POST', '/proxy/calendar/v3/freeBusy', connection=connection, body={
            'timeMin': start.isoformat(), 'timeMax': end.isoformat(), 'timeZone': 'UTC',
            'calendarExpansionMax': 10, 'items': [{'id': identifier} for identifier in selected]})
        if instant(data.get('timeMin')) > start or instant(data.get('timeMax')) < end:
            raise CalendarUnavailable()
        calendars = data.get('calendars')
        if not isinstance(calendars, dict):
            raise CalendarUnavailable()
        intervals = []
        for identifier in selected:
            value = calendars.get(identifier)
            if not isinstance(value, dict) or value.get('errors') or not isinstance(value.get('busy'), list) or len(value['busy']) > 5000:
                raise CalendarUnavailable()
            for interval in value['busy']:
                if not isinstance(interval, dict):
                    raise CalendarUnavailable()
                a, b = instant(interval.get('start')), instant(interval.get('end'))
                if b <= a:
                    raise CalendarUnavailable()
                intervals.append((a, b))
        return intervals
