"""Bounded private extraction and cost updates; a parse failure never loses a file."""
import json
import os
import signal
import subprocess
import sys
import tempfile
from threading import BoundedSemaphore

slots = BoundedSemaphore(1)


def extract_total(data, mime):
    if not slots.acquire(blocking=False):
        return {'status': 'unavailable'}
    try:
        with tempfile.TemporaryDirectory(prefix='plus-receipt-total-') as directory, subprocess.Popen(
                [sys.executable, '-m', 'estimoto_plus.receipt_total_worker', mime, directory],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                start_new_session=True, env={'PATH': os.environ.get('PATH','/usr/bin:/bin'),
                    'LANG':'C.UTF-8', 'OMP_THREAD_LIMIT': '1'}) as process:
            try:
                output, _ = process.communicate(data, timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                return {'status': 'unavailable'}
            if process.returncode or len(output) > 65536:
                return {'status': 'unavailable'}
            result = json.loads(output)
            if not isinstance(result, dict) or result.get('status') not in {
                'ready', 'needs_review', 'not_found', 'unsupported_currency', 'unavailable'}:
                return {'status': 'unavailable'}
            amount = result.get('amount_cents')
            if amount is not None and (type(amount) is not int or not 0 <= amount <= 100_000_000 or result.get('currency') != 'USD'):
                return {'status': 'needs_review'}
            items = result.get('work_items', [])
            if not isinstance(items, list) or len(items) > 40 or any(
                not isinstance(item, dict) or not isinstance(item.get('title'), str) or len(item['title']) > 180
                or any(not isinstance(item.get(key, []), list) or len(item.get(key, [])) > 24
                    or any(not isinstance(v, str) or len(v) > 180 for v in item.get(key, [])) for key in ('tasks', 'parts'))
                or (item.get('amount_cents') is not None and (type(item['amount_cents']) is not int or not 0 <= item['amount_cents'] <= 100_000_000))
                for item in items
            ):
                result = {**result, 'work_items': [], 'items_status': 'needs_review'}
            return result
    except Exception:
        return {'status': 'unavailable'}
    finally:
        slots.release()


def apply_extraction(receipt, record, result):
    receipt.total_extraction = dict(result)
    if result.get('status') == 'ready' and type(result.get('amount_cents')) is int and record.cost_cents is None:
        record.cost_cents = result['amount_cents']
        receipt.total_extraction = {**result, 'status': 'applied'}
