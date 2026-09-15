"""Customer-initiated account deletion.

Every table that reaches `customers` through foreign keys is cleared for the
customer, children first, so nothing private survives: vehicles, estimates
and their photos, requests and their outbox copies, reminders, saved shops,
history, receipts, calendar and Gmail bindings, budgets and rate buckets.
Private files are removed after the rows. When a Supabase service-role key
is configured the sign-in identity itself is deleted as well; otherwise the
identity remains and a later sign-in starts an empty account.
"""
import logging
from collections import deque
from pathlib import Path

import httpx
from sqlalchemy import delete, select

from .capture_models import CaptureReceipt
from .graph_models import KnowledgeReceipt
from .models import Base, Estimate, Photo, Vehicle

log = logging.getLogger(__name__)


def _paths():
    """Shortest foreign-key path from each table to customers, as (column, referred column) hops."""
    customers = Base.metadata.tables['customers']
    paths = {customers: []}
    edges = {}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            for fk in column.foreign_keys:
                edges.setdefault(fk.column.table, []).append((table, column, fk.column))
    queue = deque([customers])
    while queue:
        parent = queue.popleft()
        for table, column, referred in edges.get(parent, []):
            if table in paths:
                continue
            paths[table] = [(column, referred)] + paths[parent]
            queue.append(table)
    return paths


def _owned(path, customer_id):
    """A filter selecting rows whose FK chain ends at the customer."""
    column, referred = path[0]
    rest = path[1:]
    if not rest:
        return column == customer_id
    return column.in_(select(referred).where(_owned(rest, customer_id)))


def private_files(db, settings, customer_id):
    root = Path(settings.photo_dir)
    files = []
    for name in db.scalars(select(Vehicle.image_storage_name).where(Vehicle.customer_id == customer_id)).all():
        if name:
            files.append(root / 'vehicle-images' / name)
    for name in db.scalars(select(Photo.storage_name).join(Estimate, Estimate.id == Photo.estimate_id)
                           .where(Estimate.customer_id == customer_id)).all():
        files.append(root / name)
    for name in db.scalars(select(KnowledgeReceipt.storage_name).where(KnowledgeReceipt.customer_id == customer_id)).all():
        if name:
            files.append(root / 'receipts' / name)
    for replaced in db.scalars(select(CaptureReceipt.replaced_storage).where(CaptureReceipt.customer_id == customer_id)).all():
        for name in replaced or []:
            if isinstance(name, str):
                files.append(root / name)
    # Storage names are UUIDs; anything else never leaves the photo directory.
    return [f for f in files if f.resolve().is_relative_to(root.resolve())]


def delete_customer_data(db, settings, customer_id):
    files = private_files(db, settings, customer_id)
    paths = _paths()
    counts = {}
    for table in reversed(Base.metadata.sorted_tables):
        path = paths.get(table)
        if path is None or table.name == 'customers':
            continue
        removed = db.execute(delete(table).where(_owned(path, customer_id))).rowcount
        if removed:
            counts[table.name] = removed
    db.execute(delete(Base.metadata.tables['customers']).where(Base.metadata.tables['customers'].c.id == customer_id))
    db.commit()
    for file in files:
        try:
            file.unlink(missing_ok=True)
        except OSError:
            log.warning('Private file cleanup failed during account deletion')
    return counts


def delete_auth_identity(settings, customer_id, transport=None):
    """Delete the Supabase user. Returns True, False on failure, or None when not configured."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    url = settings.supabase_url.rstrip('/') + '/auth/v1/admin/users/' + httpx.URL(path=customer_id).path.lstrip('/')
    try:
        with httpx.Client(timeout=httpx.Timeout(8, connect=3), transport=transport, follow_redirects=False, trust_env=False) as client:
            response = client.delete(url, headers={'apikey': settings.supabase_service_role_key,
                                                   'Authorization': f'Bearer {settings.supabase_service_role_key}'})
    except httpx.HTTPError:
        log.warning('Supabase identity deletion failed: network')
        return False
    if response.status_code in (200, 204, 404):
        return True
    log.warning('Supabase identity deletion failed: %s', response.status_code)
    return False
