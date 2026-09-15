"""Bounded YouTube Data API search for Estibot care topics.

Search results are cached per query for seven days and charged against a
daily budget before any network I/O, so a quota-heavy search (100 units of
the 10,000-unit daily default) never runs twice for the same vehicle and
topic. Any provider failure returns no videos and the caller keeps the plain
YouTube search link. Provider error bodies never reach the customer.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import Integer, String, delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .discovery_models import DirectoryCache
from .models import Base, now

ORIGIN = 'https://www.googleapis.com'
VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
CACHE_TTL = timedelta(days=7)
MAX_RESULTS = 3


class YoutubeBudget(Base):
    __tablename__ = 'youtube_search_budget'
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)


class YoutubeUnavailable(Exception):
    pass


def configured(settings):
    return bool(settings.youtube_enabled and settings.youtube_api_key)


def utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def clean(value, limit):
    if not isinstance(value, str):
        return ''
    return ' '.join(value.split())[:limit]


def cache_key(query):
    return 'youtube:' + hashlib.sha256(query.lower().encode()).hexdigest()[:60]


def normalize(item):
    if not isinstance(item, dict):
        return None
    identifier = item.get('id')
    identifier = identifier.get('videoId') if isinstance(identifier, dict) else None
    snippet = item.get('snippet')
    if not isinstance(identifier, str) or not VIDEO_ID.fullmatch(identifier) or not isinstance(snippet, dict):
        return None
    title, channel = clean(snippet.get('title'), 200), clean(snippet.get('channelTitle'), 120)
    if not title or not channel:
        return None
    published = snippet.get('publishedAt')
    if published is not None:
        try:
            published = datetime.fromisoformat(str(published).replace('Z', '+00:00')).date().isoformat()
        except ValueError:
            published = None
    return {'video_id': identifier, 'title': title, 'channel': channel, 'published_at': published,
            'url': f'https://www.youtube.com/watch?v={identifier}',
            'source': f'YouTube · {channel} · review vehicle compatibility'}


def reserve_request(factory, settings):
    current = now()
    day = current.date().isoformat()
    with factory() as db:
        if db.get(YoutubeBudget, day) is None:
            try:
                with db.begin_nested():
                    db.add(YoutubeBudget(day=day, requests=0))
                    db.flush()
            except IntegrityError:
                pass
        limit = max(0, min(500, settings.youtube_daily_requests))
        changed = db.execute(update(YoutubeBudget).where(YoutubeBudget.day == day, YoutubeBudget.requests < limit)
                             .values(requests=YoutubeBudget.requests + 1)).rowcount
        if not changed:
            raise YoutubeUnavailable('budget_exhausted')
        db.execute(delete(YoutubeBudget).where(YoutubeBudget.day < (current - timedelta(days=14)).date().isoformat()))
        db.commit()  # Charge before I/O, including failures and process crashes.


def _fetch(transport, settings, query):
    params = {'part': 'snippet', 'type': 'video', 'safeSearch': 'strict', 'videoEmbeddable': 'true',
              'relevanceLanguage': 'en', 'maxResults': 10, 'q': query, 'key': settings.youtube_api_key}
    try:
        started = time.monotonic()
        with httpx.Client(transport=transport, timeout=httpx.Timeout(8, connect=3), follow_redirects=False, trust_env=False) as client:
            with client.stream('GET', ORIGIN + '/youtube/v3/search', params=params,
                               headers={'Accept-Encoding': 'identity'}) as response:
                if response.status_code != 200:
                    raise YoutubeUnavailable('provider_error')
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=1024):
                    if len(data) + len(chunk) > 512 * 1024 or time.monotonic() - started > 10:
                        raise YoutubeUnavailable('response_limit')
                    data.extend(chunk)
        result = json.loads(data)
        items = result.get('items') if isinstance(result, dict) else None
        if not isinstance(items, list) or len(items) > 50:
            raise YoutubeUnavailable('invalid_response')
    except (httpx.HTTPError, ValueError, TypeError, RecursionError):
        raise YoutubeUnavailable('provider_unavailable') from None
    videos, seen = [], set()
    for item in items:
        video = normalize(item)
        if video and video['video_id'] not in seen:
            seen.add(video['video_id'])
            videos.append(video)
        if len(videos) == MAX_RESULTS:
            break
    return videos


def search_videos(factory, transport, settings, query):
    """Return up to three verified videos for the query, or an empty list."""
    query = clean(query, 200)
    if not configured(settings) or not query:
        return []
    key = cache_key(query)
    with factory() as db:
        row = db.get(DirectoryCache, key)
        if row and row.fetched_at and utc(row.fetched_at) > now() - CACHE_TTL:
            videos = row.value.get('videos', [])
            return [v for v in videos if isinstance(v, dict)][:MAX_RESULTS]
    try:
        reserve_request(factory, settings)
        videos = _fetch(transport, settings, query)
    except YoutubeUnavailable:
        return []
    with factory() as db:
        row = db.get(DirectoryCache, key)
        if row is None:
            row = DirectoryCache(key=key, value={})
            db.add(row)
        row.value, row.fetched_at = {'query': query, 'videos': videos}, now()
        db.commit()
    return videos
