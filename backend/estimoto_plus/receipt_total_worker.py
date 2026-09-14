"""Sandboxed local text/OCR worker. Stdout contains only a bounded amount result."""
import csv
from contextlib import nullcontext
from decimal import Decimal
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
import resource
import subprocess
import sys
import tempfile
from .receipt_work_items import parse_work_items

TOTAL = re.compile(r'(?<!\w)(grand[ \t]+total|invoice[ \t]+total|total(?:[ \t]+(?:amount(?:[ \t]+paid)?|paid|due|price|charges))?|amount[ \t]+paid)'
    r'[\s:.]*(?:(?:USD|US\$|\$)\s*)?((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?![\d.,])', re.I)


def parse_total(text, confidences=None):
    if len(text) > 200_000:
        return {'status': 'needs_review'}
    if re.search(r'\b(?:CAD|AUD|NZD|EUR|GBP|JPY|MXN|CHF)\b|[€£¥]', text, re.I):
        return {'status': 'unsupported_currency'}
    candidates = []
    for match in TOTAL.finditer(text):
        cents = int(Decimal(match[2].replace(',', '')) * 100)
        if cents > 100_000_000:
            continue
        label = match[1].casefold()
        priority = 2 if label.startswith(('grand', 'invoice')) else 1 if label.startswith('total') else 0
        line = text[:match.start()].count('\n')
        confidence = min((confidences or [100])[line:line + match[0].count('\n') + 1] or [0]) if confidences else 100
        candidates.append((priority, cents, confidence))
    if not candidates:
        return {'status': 'not_found'}
    priority = max(c[0] for c in candidates)
    chosen = [c for c in candidates if c[0] == priority]
    amounts = {c[1] for c in chosen}
    if len(amounts) != 1:
        return {'status': 'needs_review'}
    confidence = min(c[2] for c in chosen)
    return {'status': 'ready' if confidence >= 85 else 'needs_review',
            'amount_cents': amounts.pop(), 'currency': 'USD', 'confidence': round(confidence)}


def command(args, *, timeout=7):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=timeout, check=True).stdout


def ocr(path):
    from PIL import Image, ImageOps
    with Image.open(path) as source:
        picture = ImageOps.exif_transpose(source).convert('RGB')
        picture.thumbnail((2600,2600))
        if max(picture.size) < 1500:
            factor = min(3, 1500 / max(picture.size))
            picture = picture.resize((int(picture.width * factor), int(picture.height * factor)))
        prepared = path.with_name('ocr-input.png')
        picture.save(prepared)
    data = command(['tesseract', str(prepared), 'stdout', '-l', 'eng', '--psm', '6', 'tsv']).decode('utf-8')
    groups = {}
    for row in csv.DictReader(StringIO(data), delimiter='\t'):
        if row.get('text', '').strip() and float(row.get('conf', '-1')) >= 0:
            key = tuple(row.get(k) for k in ('page_num', 'block_num', 'par_num', 'line_num'))
            groups.setdefault(key, []).append((row['text'], float(row['conf'])))
    lines = [' '.join(word for word, _ in words) for words in groups.values()]
    confidence = [min(c for _, c in words) for words in groups.values()]
    return lines, confidence


def extract(data, mime, directory=None):
    with (nullcontext(directory) if directory else tempfile.TemporaryDirectory(prefix='plus-receipt-total-')) as directory:
        root = Path(directory)
        original = root / ('receipt.pdf' if mime == 'application/pdf' else 'receipt.image')
        original.write_bytes(data)
        if mime == 'application/pdf':
            text = command(['pdftotext', '-layout', '-nopgbrk', '-enc', 'UTF-8', str(original), '-']).decode('utf-8')
            found = parse_total(text)
            if found['status'] != 'not_found':
                return {**found, **parse_work_items(text), 'source': 'pdf_text'}
            from pypdf import PdfReader
            pages = len(PdfReader(BytesIO(data)).pages)
            if pages > 3:
                return {'status': 'not_found', **parse_work_items(text), 'source': 'pdf_text'}
            command(['pdftoppm', '-scale-to', '2200', '-png', str(original), str(root / 'page')])
            images = sorted(root.glob('page-*.png'))
            source = 'scanned_pdf_ocr'
        elif mime in {'image/png', 'image/jpeg', 'image/webp'}:
            images, source = [original], 'photo_ocr'
        else:
            return {'status': 'unavailable'}
        lines, confidence = [], []
        for page in images:
            page_lines, page_confidence = ocr(page)
            lines.extend(page_lines); confidence.extend(page_confidence)
        return {**parse_total('\n'.join(lines), confidence), **parse_work_items('\n'.join(lines), confidence), 'source': source}


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (12,12))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024,32 * 1024 * 1024))
    if sys.platform == 'linux':
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,256 * 1024 * 1024))
    try:
        data = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise ValueError('size')
        result = extract(data, sys.argv[1], sys.argv[2])
    except Exception:
        result = {'status': 'unavailable'}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
