"""Source-declared Commons photos with bounded, verified credit metadata."""
from html.parser import HTMLParser
import re
from urllib.parse import quote, urlencode

MAX_FILES = 20
MAX_METADATA_BYTES = 256 * 1024
_RASTER = re.compile(r'\.(?:jpe?g|png|webp)$', re.IGNORECASE)


def commons_file(tags):
    """Accept only a single Commons File reference, never an arbitrary image URL."""
    for key in ('wikimedia_commons', 'image'):
        value = tags.get(key)
        if not isinstance(value, str) or not value.startswith('File:'):
            continue
        filename = value[5:].strip().replace('_', ' ')
        if (not 1 <= len(filename) <= 160 or not _RASTER.search(filename) or
                any(c in filename for c in '/\\%?#:|<>[]{}') or
                any(ord(c) < 32 for c in filename) or '..' in filename):
            continue
        return 'File:' + filename
    return None


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _credit(metadata, key, limit):
    row = metadata.get(key)
    value = row.get('value') if isinstance(row, dict) else None
    if not isinstance(value, str) or not 1 <= len(value) <= 2000:
        return None
    parser = _PlainText()
    try:
        parser.feed(value)
        text = ' '.join(' '.join(parser.parts).split())
    except ValueError:
        return None
    if not 1 <= len(text) <= limit or any(ord(c) < 32 for c in text):
        return None
    return text


def _media(title, image):
    if not isinstance(image, dict) or image.get('mime') not in ('image/jpeg', 'image/png', 'image/webp'):
        return None
    metadata = image.get('extmetadata')
    if not isinstance(metadata, dict):
        return None
    artist = _credit(metadata, 'Artist', 120)
    license_name = _credit(metadata, 'LicenseShortName', 80)
    if (not artist or artist.casefold() in ('unknown', 'anonymous', 'unspecified', 'n/a') or
            not license_name or license_name.casefold() in ('unknown', 'unspecified', 'n/a')):
        return None
    filename = quote(title[5:].replace(' ', '_'), safe='')
    return {'url': 'https://commons.wikimedia.org/wiki/Special:Redirect/file/' + filename + '?width=320',
            'kind': 'photo', 'attribution': artist + ' · ' + license_name,
            'source_url': 'https://commons.wikimedia.org/wiki/File:' + filename}


def verified_commons_media(titles, transport, read_public, *, limit, meter):
    """One fixed-host imageinfo batch per cached OSM refresh; failures omit photos."""
    titles = list(dict.fromkeys(titles))[:MAX_FILES]
    if not titles or limit < 4096:
        return {}
    query = urlencode({'action': 'query', 'format': 'json', 'formatversion': '2',
                       'prop': 'imageinfo', 'titles': '|'.join(titles),
                       'iiprop': 'mime|extmetadata',
                       'iiextmetadatafilter': 'Artist|LicenseShortName',
                       'iilimit': '1'})
    data = read_public('GET', 'https://commons.wikimedia.org/w/api.php?' + query, transport,
                       limit=min(limit, MAX_METADATA_BYTES), meter=meter)
    pages = data.get('query', {}).get('pages') if isinstance(data.get('query'), dict) else None
    if not isinstance(pages, list) or len(pages) > MAX_FILES:
        return {}
    wanted = {title.replace('_', ' ').casefold(): title for title in titles}
    result = {}
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get('title'), str):
            continue
        title = wanted.get(page['title'].replace('_', ' ').casefold())
        images = page.get('imageinfo')
        if title and isinstance(images, list) and len(images) == 1:
            media = _media(title, images[0])
            if media:
                result[title] = media
    return result
