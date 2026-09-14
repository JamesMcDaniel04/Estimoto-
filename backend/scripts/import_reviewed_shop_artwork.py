"""Package reviewed official business thumbnails. Does not fetch URLs or deploy.

Inputs are human/agent-reviewed JSON manifests and local raster originals. The
output retains exact public listing identities, source credits and file hashes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from estimoto_plus.shop_media_catalog import ASSET_DIR, SOURCE, official_url
from estimoto_plus.reviewed_shops import valid_business


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests', nargs='+', type=Path)
    parser.add_argument('--review-output', type=Path, required=True)
    parser.add_argument('--partners', type=Path, help='Reviewed exact participating-provider website bindings.')
    args = parser.parse_args()
    entries, businesses, review, seen = [], [], [], set()
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for manifest in args.manifests:
        rows = json.loads(manifest.read_text())
        if not isinstance(rows, list) or len(rows) > 2000:
            raise ValueError('Expected a bounded reviewed manifest array.')
        for row in rows:
            source_id = row['source_id']
            if not SOURCE.fullmatch(source_id) or source_id in seen:
                raise ValueError('Invalid or duplicate public listing reference.')
            seen.add(source_id)
            # Local paths never enter the public application or review record.
            audit = {k: row[k] for k in ('source_id', 'name', 'address', 'status',
                                        'source_url', 'asset_url', 'kind', 'attribution',
                                        'evidence', 'reason') if k in row}
            audit['business_verified'] = row.get('business_verified', False)
            if row.get('business_verified'):
                business = row['business']
                if not valid_business(business):
                    raise ValueError('Invalid reviewed business profile: ' + row['name'])
                businesses.append(business)
                audit['business'] = business
            if row['status'] != 'verified':
                if row['status'] != 'unavailable' or not row.get('reason'):
                    raise ValueError('Unresolved entries must state why artwork is unavailable.')
                review.append(audit)
                continue
            if (not official_url(row.get('source_url')) or row.get('kind') not in ('logo', 'photo') or
                    not row.get('evidence') or not row.get('attribution') or
                    urlsplit(row.get('asset_url', '')).scheme not in ('https', 'http')):
                raise ValueError('Verified images require public sources, identity evidence and credit.')
            path = Path(row['local_path'])
            if path.is_symlink() or not 1 <= path.stat().st_size <= 10 * 1024 * 1024:
                raise ValueError('Invalid reviewed raster file.')
            with Image.open(path) as original:
                if original.width * original.height > 16_000_000:
                    raise ValueError('Reviewed image exceeds pixel limit.')
                image = ImageOps.exif_transpose(original).convert('RGBA')
                image.thumbnail((320, 320), Image.Resampling.LANCZOS)
                from io import BytesIO
                out = BytesIO()
                image.save(out, 'PNG', optimize=True)
                data = out.getvalue()
            if len(data) > 512 * 1024:
                raise ValueError('Normalized thumbnail exceeds byte limit.')
            digest = hashlib.sha256(data).hexdigest()
            (ASSET_DIR / (digest + '.png')).write_bytes(data)
            entry = {k: row[k] for k in ('source_id', 'name', 'address', 'source_url',
                                         'kind', 'attribution', 'evidence')}
            entry['sha256'] = digest
            entry['background'] = 'dark' if row.get('background') == 'dark' else 'light'
            entries.append(entry)
            audit['sha256'] = digest
            review.append(audit)
    checked_at = datetime.now(timezone.utc).isoformat()
    (ASSET_DIR / 'catalog.json').write_text(json.dumps({
        'schema': 1, 'checked_at': checked_at, 'shops': entries, 'businesses': businesses, 'brands': [],
        'partners': json.loads(args.partners.read_text()) if args.partners else [],
    }, indent=2) + '\n')
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    args.review_output.write_text(json.dumps({
        'checked_at': checked_at, 'listings_reviewed': len(review),
        'verified_images': len(entries), 'unavailable_images': len(review) - len(entries),
        'verified_businesses': len(businesses),
        'scope': 'Public listings shown with participating Demolition Dent for ZIP 80204.',
        'source_attribution': 'Public listing identities: OpenStreetMap contributors, ODbL-1.0. '
                              'Business artwork remains attributed to its publisher; no affiliation is implied.',
        'listings': review,
    }, indent=2) + '\n')
    print(json.dumps({'reviewed': len(review), 'verified': len(entries), 'unavailable': len(review) - len(entries)}))


if __name__ == '__main__':
    main()
