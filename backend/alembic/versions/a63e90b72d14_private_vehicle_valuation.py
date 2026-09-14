"""Bounded private vehicle valuation cache and provider budget.

Revision ID: a63e90b72d14
Revises: d81a46bc720e
"""
from alembic import op
import sqlalchemy as sa

revision = 'a63e90b72d14'
down_revision = 'd81a46bc720e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('vehicle_valuation_cache',
        sa.Column('vehicle_id', sa.String(36), sa.ForeignKey('vehicles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('customer_id', sa.String(100), sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retry_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lease_token', sa.String(36), nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_vehicle_valuation_cache_customer_id', 'vehicle_valuation_cache', ['customer_id'])
    op.create_table('valuation_provider_state',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('day_bucket', sa.Integer(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('blocked_until', sa.DateTime(timezone=True), nullable=True))
    if op.get_bind().dialect.name == 'postgresql':
        for table in ('vehicle_valuation_cache', 'valuation_provider_state'):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'REVOKE ALL ON "{table}" FROM PUBLIC')
            for role in ('anon', 'authenticated'):
                op.execute(sa.text(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON {table} FROM {role}; END IF; END $$"))


def downgrade():
    op.drop_table('vehicle_valuation_cache')
    op.drop_table('valuation_provider_state')
