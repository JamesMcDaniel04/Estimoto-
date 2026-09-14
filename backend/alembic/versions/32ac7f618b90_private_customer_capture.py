"""Private capture replay receipts and VIN suggestions.

Revision ID: 32ac7f618b90
Revises: e96b17c4d502
"""
from alembic import op
import sqlalchemy as sa

revision = '32ac7f618b90'
down_revision = 'e96b17c4d502'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('customer_capture_receipts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('customer_id', sa.String(100), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('estimate_id', sa.String(36), sa.ForeignKey('estimates.id'), nullable=False),
        sa.Column('capture_key', sa.String(100), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('claim_token', sa.String(36), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('replaced_storage', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('customer_capture_vin_suggestions',
        sa.Column('photo_id', sa.String(36), sa.ForeignKey('photos.id'), primary_key=True),
        sa.Column('customer_id', sa.String(100), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('estimate_id', sa.String(36), sa.ForeignKey('estimates.id'), nullable=False),
        sa.Column('photo_sha256', sa.String(64), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    for table in ('customer_capture_receipts', 'customer_capture_vin_suggestions'):
        for column in ('customer_id', 'estimate_id'):
            op.create_index(f'ix_{table}_{column}', table, [column])
        if op.get_bind().dialect.name == 'postgresql':
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'REVOKE ALL ON "{table}" FROM PUBLIC')
            for role in ('anon', 'authenticated'):
                op.execute(sa.text(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON \"{table}\" FROM {role}; END IF; END $$"))


def downgrade():
    op.drop_table('customer_capture_vin_suggestions')
    op.drop_table('customer_capture_receipts')
