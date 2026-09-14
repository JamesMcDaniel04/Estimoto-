from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject

from test_knowledge import clients, add
from test_api import create_vehicle, h
from test_receipts import upload, image


def text_pdf(text):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    content = DecodedStreamObject()
    lines = ['BT /F1 18 Tf 50 740 Td']
    for line in text.splitlines():
        lines.append('(' + line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') + ') Tj 0 -28 Td')
    content.set_data(('\n'.join(lines) + '\nET').encode())
    page[NameObject('/Contents')] = writer._add_object(content)
    output = BytesIO(); writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize('text,cents', [
    ('Subtotal: $1,660.80\nSales Tax: $42.68\nTerms: GRAND TOTAL: $1,703.48\nTotal Labor: $764.17\nBalance due: $0.00',170348),
    ('Subtotal 100.00\nTax 8.25\nTOTAL $108.25',10825),
    ('Grand Total\nUSD 1,703.48\nGrand Total $1,703.48',170348),
    ('Total amount: $0.00',0),
])
def test_total_selection_ignores_components_and_paid_balance(text,cents):
    from estimoto_plus.receipt_total_worker import parse_total
    result = parse_total(text)
    assert result['amount_cents'] == cents and result['status'] == 'ready'


@pytest.mark.parametrize('text', ['Subtotal $50.00\nTax $4.00', 'Total $20.00\nTotal $30.00',
    'TOTAL CAD $120.00', 'TOTAL €120.00', 'TOTAL -$100.00', 'Grand Total $1000001.00'])
def test_ambiguous_unsupported_or_missing_totals_are_not_applied(text):
    from estimoto_plus.receipt_total_worker import parse_total
    assert parse_total(text)['status'] != 'ready'


def test_pdf_upload_records_total_once_and_retains_it_when_receipt_deleted(clients):
    client, _ = clients
    rid = add(client, create_vehicle(client)).json()['id']
    key = str(uuid4())
    data = text_pdf('Synthetic QA invoice\nSubtotal $100.00\nTax $8.25\nGRAND TOTAL $108.25\nPAID\nBalance due $0.00')
    first = upload(client, rid, key, data=data, mime='application/pdf').json()
    assert first['total_extraction']['status'] == 'applied'
    assert first['total_extraction']['amount_cents'] == 10825
    assert upload(client, rid, key, data=data, mime='application/pdf').json() == first
    record = client.get('/v1/knowledge', headers=h('alice')).json()['records'][0]
    assert record['cost_cents'] == 10825
    second = upload(client, rid, data=data, mime='application/pdf').json()
    assert second['total_extraction']['status'] == 'ready'
    assert client.get('/v1/knowledge', headers=h('alice')).json()['records'][0]['cost_cents'] == 10825
    assert client.delete(f"/v1/knowledge/records/{rid}/receipts/{first['id']}", headers=h('alice')).status_code == 204
    assert client.get('/v1/knowledge', headers=h('alice')).json()['records'][0]['cost_cents'] == 10825


def test_existing_cost_is_preserved_and_detected_total_can_be_reviewed_with_conflict_guard(clients):
    client, _ = clients
    rid = add(client, create_vehicle(client), cost_cents=5000).json()['id']
    receipt = upload(client, rid, data=text_pdf('TOTAL $108.25'), mime='application/pdf').json()
    assert receipt['total_extraction']['status'] == 'ready'
    assert client.get('/v1/knowledge', headers=h('alice')).json()['records'][0]['cost_cents'] == 5000
    path = f"/v1/knowledge/records/{rid}/receipts/{receipt['id']}/apply-total"
    assert client.post(path, headers=h('bob'), json={'expected_cost_cents':5000}).status_code == 404
    assert client.post(path, headers=h('alice'), json={'expected_cost_cents':3000}).status_code == 409
    assert client.post(path, headers=h('alice'), json={'expected_cost_cents':5000}).status_code == 200
    assert client.post(path, headers=h('alice'), json={'expected_cost_cents':5000}).status_code == 200
    assert client.get('/v1/knowledge', headers=h('alice')).json()['records'][0]['cost_cents'] == 10825


def test_ocr_photo_extracts_real_printed_total():
    from estimoto_plus.receipt_totals import extract_total
    import shutil
    if not shutil.which('tesseract'):
        pytest.fail('Tesseract is required for receipt-photo release verification')
    canvas = Image.new('RGB', (1100,600), 'white')
    draw = ImageDraw.Draw(canvas)
    # Pillow bundles scalable DejaVuSans; no host-specific font path.
    font = ImageFont.load_default(size=45)
    draw.multiline_text((60,60),'SYNTHETIC QA RECEIPT\nSubtotal $100.00\nTax $8.25\nGRAND TOTAL $108.25',fill='black',font=font,spacing=25)
    stream = BytesIO(); canvas.save(stream,format='PNG')
    result = extract_total(stream.getvalue(), 'image/png')
    assert result['status'] == 'ready' and result['amount_cents'] == 10825
    assert result['source'] == 'photo_ocr'


def test_parser_failure_does_not_fail_saved_upload_and_is_retryable(clients, monkeypatch):
    from estimoto_plus import receipt_totals
    client, _ = clients
    rid = add(client, create_vehicle(client)).json()['id']
    monkeypatch.setattr(receipt_totals,'extract_total',lambda *_: {'status':'unavailable'})
    receipt = upload(client, rid, data=image()).json()
    assert receipt['total_extraction']['status'] == 'unavailable'
    path = f"/v1/knowledge/records/{rid}/receipts/{receipt['id']}/parse-total"
    assert client.post(path, headers=h('bob')).status_code == 404
    monkeypatch.setattr(receipt_totals,'extract_total',lambda *_: {'status':'ready','amount_cents': 9999,'currency':'USD','source':'photo_ocr'})
    assert client.post(path, headers=h('alice')).json()['total_extraction']['status'] == 'applied'
    assert client.get('/v1/knowledge', headers=h('alice')).json()['records'][0]['cost_cents'] == 9999
