"""Re-read older saved receipts locally, in bounded, restartable batches.

No customer text or identity is logged, and existing recorded costs are kept.
Run after the receipt parser deploy: python -m estimoto_plus.receipt_details_backfill
"""
import argparse
import hashlib
import json
from sqlalchemy import select

from .app import create_app
from .graph import lock_customer
from .graph_models import KnowledgeReceipt, KnowledgeRecord
from .receipt_totals import extract_total, apply_extraction
from .receipts import _path, MAX_BYTES


def backfill(session_factory, settings, limit=20):
    counts={'processed':0,'with_items':0,'unavailable':0}
    with session_factory() as db:
        ids=db.execute(select(KnowledgeReceipt.id,KnowledgeReceipt.customer_id).where(
            KnowledgeReceipt.status=='saved',
            KnowledgeReceipt.total_extraction['items_version'].as_integer().is_distinct_from(1),
        ).order_by(KnowledgeReceipt.created_at).limit(limit)).all()
    for receipt_id,customer_id in ids:
        with session_factory() as db:
            lock_customer(db,customer_id)
            receipt=db.get(KnowledgeReceipt,receipt_id)
            if receipt is None or receipt.status!='saved' or (receipt.total_extraction or {}).get('items_version')==1: continue
            record=db.get(KnowledgeRecord,receipt.record_id)
            if record is None or record.customer_id!=customer_id: continue
            try:
                with _path(settings,receipt.storage_name).open('rb') as stream: data=stream.read(MAX_BYTES+1)
                if len(data)!=receipt.byte_size or hashlib.sha256(data).hexdigest()!=receipt.sha256: raise ValueError('integrity')
                result=extract_total(data,receipt.content_type)
                if result.get('status')=='unavailable':
                    counts['unavailable']+=1; continue
                apply_extraction(receipt,record,result)
                db.commit();counts['processed']+=1
                counts['with_items']+=bool(result.get('work_items'))
            except (OSError,ValueError): counts['unavailable']+=1
    return counts


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=20);args=parser.parse_args()
    if not 1<=args.limit<=50: parser.error('limit must be 1..50')
    app=create_app()
    try: print(json.dumps(backfill(app.state.session_factory,app.state.settings,args.limit)))
    finally: app.state.engine.dispose()

if __name__=='__main__': main()
