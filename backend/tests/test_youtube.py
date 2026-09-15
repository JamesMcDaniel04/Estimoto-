"""Estibot care topics link verified YouTube videos when the Data API is configured."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus import youtube


def _item(video_id, title='How to check tire pressure', channel='Demo Garage', published='2025-03-04T10:00:00Z'):
    return {'id': {'kind': 'youtube#video', 'videoId': video_id},
            'snippet': {'title': title, 'channelTitle': channel, 'publishedAt': published}}


@pytest.fixture
def stack(tmp_path):
    calls = []
    responses = []

    def transport(request):
        calls.append(request)
        status, body = responses.pop(0) if responses else (200, {'items': []})
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, content=body)

    settings = Settings(database_url=f'sqlite:///{tmp_path / "yt.sqlite"}', environment='test',
                        bridge_url='https://fixture.invalid/receive', bridge_key='fixture-key',
                        photo_dir=str(tmp_path / 'photos'), youtube_enabled=True, youtube_api_key='yt-key',
                        youtube_daily_requests=2)
    app = create_app(settings, auth_verifier=lambda token: {'id': token, 'email': f'{token}@example.test', 'confirmed_at': 'ok'})
    app.state.youtube_transport = httpx.MockTransport(transport)
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer customer'
        client.put('/v1/profile', json={'name': 'Customer', 'postal_code': '80202'})
        vehicle = client.post('/v1/vehicles', json={'year': 2024, 'make': 'Toyota', 'model': 'Camry'}).json()['id']
        yield client, vehicle, calls, responses
    app.state.engine.dispose()


def ask(client, vehicle, message='How do I do an oil service?'):
    response = client.post('/v1/assistant', json={'message': message, 'vehicle_id': vehicle})
    assert response.status_code == 200, response.text
    return response.json()


def test_unconfigured_backend_keeps_search_links_and_reports_capability(tmp_path):
    settings = Settings(database_url=f'sqlite:///{tmp_path / "plain.sqlite"}', environment='test',
                        bridge_url='https://fixture.invalid/receive', bridge_key='fixture-key', photo_dir=str(tmp_path / 'photos'))
    app = create_app(settings, auth_verifier=lambda token: {'id': token, 'email': f'{token}@example.test', 'confirmed_at': 'ok'})
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer customer'
        assert client.get('/v1/bootstrap').json()['capabilities']['youtube_search'] is False
        vehicle = client.post('/v1/vehicles', json={'year': 2024, 'make': 'Toyota', 'model': 'Camry'}).json()['id']
        result = ask(client, vehicle)
    assert [v['url'].startswith('https://www.youtube.com/results?search_query=') for v in result['videos']] == [True]


def test_enabled_without_key_refuses_to_start(tmp_path):
    with pytest.raises(ValueError):
        create_app(Settings(database_url=f'sqlite:///{tmp_path / "k.sqlite"}', environment='test', youtube_enabled=True,
                            photo_dir=str(tmp_path / 'photos')))


def test_configured_backend_returns_verified_videos_and_caches_them(stack):
    client, vehicle, calls, responses = stack
    assert client.get('/v1/bootstrap').json()['capabilities']['youtube_search'] is True
    responses.append((200, {'items': [_item('abcdefghijk'), _item('abcdefghijk'), _item('bad id!'), _item('lmnopqrstuv', channel='Tire Talk'),
                                      _item('zyxwvutsrqp'), _item('AAAAAAAAAAA')]}))
    result = ask(client, vehicle)
    assert [v['video_id'] for v in result['videos']] == ['abcdefghijk', 'lmnopqrstuv', 'zyxwvutsrqp']
    first = result['videos'][0]
    assert first['url'] == 'https://www.youtube.com/watch?v=abcdefghijk'
    assert first['source'] == 'YouTube · Demo Garage · review vehicle compatibility'
    assert first['published_at'] == '2025-03-04'
    assert len(calls) == 1
    request = calls[0]
    assert request.url.host == 'www.googleapis.com' and request.url.path == '/youtube/v3/search'
    assert request.url.params['q'] == '2024 Toyota Camry oil service'
    assert request.url.params['safeSearch'] == 'strict' and request.url.params['key'] == 'yt-key'
    # The same vehicle and topic is served from the cache without spending quota.
    again = ask(client, vehicle, 'Is there a video on how to do my oil service?')
    assert [v['video_id'] for v in again['videos']] == ['abcdefghijk', 'lmnopqrstuv', 'zyxwvutsrqp']
    assert len(calls) == 1


def test_hand_verified_tire_video_leads_retrieved_results(stack):
    client, vehicle, calls, responses = stack
    responses.append((200, {'items': [_item('abcdefghijk'), _item('lmnopqrstuv'), _item('zyxwvutsrqp')]}))
    result = ask(client, vehicle, 'How do I check tire pressure?')
    assert [v['url'] for v in result['videos']] == ['https://www.youtube.com/watch?v=dn0ShsQRgho',
                                                     'https://www.youtube.com/watch?v=abcdefghijk',
                                                     'https://www.youtube.com/watch?v=lmnopqrstuv']
    assert result['videos'][0]['source'].startswith('Michelin USA')


def test_provider_failures_fall_back_to_the_search_link(stack):
    client, vehicle, calls, responses = stack
    responses.append((500, {'error': {'message': 'quotaExceeded'}}))
    result = ask(client, vehicle)
    assert len(result['videos']) == 1 and 'results?search_query=' in result['videos'][0]['url']
    assert 'quotaExceeded' not in json.dumps(result)
    responses.append((200, b'not json'))
    result = ask(client, vehicle, 'how do I replace the air filter?')
    assert 'results?search_query=' in result['videos'][0]['url']
    assert len(calls) == 2


def test_daily_budget_is_charged_before_io_and_stops_searches(stack):
    client, vehicle, calls, responses = stack
    responses.extend([(200, {'items': [_item('abcdefghijk')]}), (200, {'items': [_item('lmnopqrstuv')]})])
    assert ask(client, vehicle, 'how do I do an oil service')['videos'][0]['video_id'] == 'abcdefghijk'
    assert ask(client, vehicle, 'how do I replace the air filter')['videos'][0]['video_id'] == 'lmnopqrstuv'
    # A third distinct topic exceeds the two-request budget: no network call, and the
    # hand-verified tire video still answers without spending quota.
    result = ask(client, vehicle, 'how do I check tire pressure')
    assert [v['url'] for v in result['videos']] == ['https://www.youtube.com/watch?v=dn0ShsQRgho']
    assert len(calls) == 2


def test_normalize_rejects_malformed_items():
    assert youtube.normalize({'id': {'videoId': 'abcdefghijk'}, 'snippet': {'title': '', 'channelTitle': 'x'}}) is None
    assert youtube.normalize({'id': 'abcdefghijk', 'snippet': {}}) is None
    video = youtube.normalize(_item('abcdefghijk', title='  Spaced   title ', published='not a date'))
    assert video['title'] == 'Spaced title' and video['published_at'] is None
