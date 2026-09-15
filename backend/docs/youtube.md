# Estibot YouTube retrieval

Care-topic answers ("how do I check tire pressure", oil service, air filter)
can link real YouTube videos for the customer's saved vehicle instead of a
search link. The hand-verified Michelin tire-pressure video always leads;
retrieved videos follow it. Any provider failure keeps the plain search link
and never reaches the customer as an error.

## Configuration

- `YOUTUBE_ENABLED=true` (the service refuses to start without a key)
- `YOUTUBE_API_KEY`: a Google Cloud API key restricted to the YouTube Data
  API v3. Keep it on the server only.
- `YOUTUBE_DAILY_REQUESTS` (default 80). A search costs 100 quota units of
  the 10,000-unit daily default, so this bounds spend to 8,000 units.

Searches use `safeSearch=strict`, embeddable videos only, and are charged
against `youtube_search_budget` (migration `a4c1e7b9d2f3`) before any network
I/O. Results are cached per vehicle and topic for seven days in the public
directory cache. Each video carries `video_id`, `title`, `channel`,
`published_at`, a watch `url` and a `source` label naming the channel and
asking the customer to confirm vehicle compatibility. `capabilities.
youtube_search` reports whether retrieval is configured for the session; demo
sessions never search.
