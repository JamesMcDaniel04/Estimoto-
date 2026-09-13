"""Preserve pending cancellations created before immutable payloads.

Revision ID: d752dbef8104
Revises: 624d7840c228
"""
import hashlib
import json
from alembic import op
import sqlalchemy as sa

revision = 'd752dbef8104'
down_revision = '624d7840c228'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    metadata = sa.MetaData()
    outbox = sa.Table('outbox', metadata, autoload_with=connection)
    requests = sa.Table('service_requests', metadata, autoload_with=connection)
    providers = sa.Table('providers', metadata, autoload_with=connection)
    rows = connection.execute(sa.select(
        outbox.c.id, outbox.c.request_id, providers.c.source_id,
    ).select_from(outbox.join(requests, outbox.c.request_id == requests.c.id)
                  .join(providers, requests.c.provider_id == providers.c.id))
      .where(outbox.c.kind == 'cancel', outbox.c.receipt_id.is_(None),
             outbox.c.payload.is_(None))).all()
    for row in rows:
        # A persisted cancellation is already customer-authorized. Only its
        # non-PII routing envelope is reconstructed; legacy creation stays closed.
        payload = {'event': 'cancelled', 'request_id': row.request_id,
                   'provider_source_id': row.source_id}
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        connection.execute(outbox.update().where(outbox.c.id == row.id).values(
            payload=payload, payload_hash=hashlib.sha256(canonical.encode()).hexdigest(),
            suppressed=False, claim_token=None, lease_until=None,
        ))


def downgrade():
    # Preserve authorized cancellation envelopes during rollback as well.
    pass
