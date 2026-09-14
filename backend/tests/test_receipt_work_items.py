from uuid import uuid4

from estimoto_plus.receipt_work_items import parse_work_items
from test_receipt_totals import text_pdf
from test_knowledge import clients, add
from test_api import create_vehicle, h
from test_receipts import upload


def test_shop_sections_preserve_work_and_parts_not_recommendations_or_legal_text():
    text = '''Shop invoice
SERVICES
1      Multi-point inspection
       LABOR
       Road Test                                Labor: $50.00
       Retrieve Diagnostic Trouble Codes
                                                SUBTOTAL: $50.00
2      Replace brake pads
       LABOR
       Replace brake pads
                                                SUBTOTAL: $250.00
       PARTS                 PART #      QTY     EACH       TOTAL
       Ceramic pad set       ABC123      1.0     $150.00    $150.00
       with sensors
Terms of Service:
1      Authorize us to drive your car
RECOMMENDED REPAIRS
3      Replace transmission
       LABOR
       Replace transmission                     SUBTOTAL: $5000.00
'''
    result = parse_work_items(text)
    assert [i['title'] for i in result['work_items']] == ['Multi-point inspection','Replace brake pads']
    assert result['work_items'][0]['tasks'] == ['Road Test','Retrieve Diagnostic Trouble Codes']
    assert result['work_items'][1]['parts'] == ['Ceramic pad set with sensors']
    assert result['work_items'][1]['amount_cents'] == 25000


def test_flat_photo_rows_ignore_totals_tax_payment_and_duplicate_lines():
    result = parse_work_items('Synthetic repair invoice\nOil change 1 $100.00\nOil change 1 $100.00\nLabor brake inspection $20.00\nTax $9.90\nTOTAL $129.90\nPaid Visa $129.90')
    assert [i['title'] for i in result['work_items']] == ['Oil change','Labor brake inspection']
    assert result['items_status'] == 'ready'


def test_unclear_ocr_is_marked_and_foreign_item_amounts_are_not_usd():
    result = parse_work_items('Oil service $100.00\nTOTAL CAD $100.00',[62,98])
    assert result['items_status'] == 'needs_review'
    assert 'amount_cents' not in result['work_items'][0]
    assert parse_work_items('Payment $500.00\nBalance due $0.00')['work_items'] == []


def test_upload_and_reread_keep_one_record_cost_and_remove_private_item_details(clients):
    client, _ = clients
    rid = add(client, create_vehicle(client), cost_cents=12345).json()['id']
    key = str(uuid4())
    data = text_pdf('Repair invoice\nOil change $100.00\nBrake inspection $20.00\nTax $9.90\nGRAND TOTAL $129.90')
    receipt = upload(client,rid,key,data=data,mime='application/pdf').json()
    assert len(receipt['total_extraction']['work_items']) == 2
    assert receipt['record_cost_cents'] == 12345
    assert upload(client,rid,key,data=data,mime='application/pdf').json() == receipt
    path=f"/v1/knowledge/records/{rid}/receipts/{receipt['id']}"
    assert client.post(path+'/parse-total',headers=h('bob')).status_code == 404
    reread=client.post(path+'/parse-total',headers=h('alice')).json()
    assert reread['total_extraction']['work_items'] == receipt['total_extraction']['work_items']
    assert reread['record_cost_cents'] == 12345
    record=client.get('/v1/knowledge',headers=h('alice')).json()['records'][0]
    assert len(record['receipts']) == 1
    assert record['receipts'][0]['total_extraction']['work_items'][0]['title'] == 'Oil change'
    assert client.delete(path,headers=h('alice')).status_code == 204
    record=client.get('/v1/knowledge',headers=h('alice')).json()['records'][0]
    assert record['receipts'] == [] and record['cost_cents'] == 12345


def test_backfill_populates_older_receipt_details_once_without_overwriting_cost(clients):
    from estimoto_plus.graph_models import KnowledgeReceipt
    from estimoto_plus.receipt_details_backfill import backfill
    client, _ = clients
    rid=add(client,create_vehicle(client),cost_cents=7777).json()['id']
    receipt=upload(client,rid,data=text_pdf('Oil service $100.00\nTOTAL $100.00'),mime='application/pdf').json()
    with client.app.state.session_factory() as db:
        row=db.get(KnowledgeReceipt,receipt['id']);row.total_extraction={'status':'ready','amount_cents':10000,'currency':'USD'};db.commit()
    result=backfill(client.app.state.session_factory,client.app.state.settings,1)
    assert result=={'processed':1,'with_items':1,'unavailable':0}
    assert backfill(client.app.state.session_factory,client.app.state.settings,1)['processed']==0
    record=client.get('/v1/knowledge',headers=h('alice')).json()['records'][0]
    assert record['cost_cents']==7777
    assert record['receipts'][0]['total_extraction']['work_items'][0]['title']=='Oil service'
