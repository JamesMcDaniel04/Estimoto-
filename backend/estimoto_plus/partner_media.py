"""The original owner's published logo route is the only partner image source."""
import re
from urllib.parse import urlsplit


def valid_partner_media(media, *, source_id, name, bridge_url):
    if media is None:
        return True
    if (media.kind != 'logo' or media.attribution != name or
            media.source_url != 'https://www.estimoto.io' or
            not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', source_id)):
        return False
    try:
        bridge = urlsplit(bridge_url)
        image = urlsplit(media.url)
    except ValueError:
        return False
    return (bridge.scheme == image.scheme == 'https' and bridge.netloc == image.netloc and
            image.username is None and image.password is None and not image.query and not image.fragment and
            image.path == '/public/plus/providers/' + source_id + '/logo')
