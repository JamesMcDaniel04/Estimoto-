"""Private per-vehicle valuation history.

Revision ID: b7f2c9d4e1a0
Revises: a63e90b72d14
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7f2c9d4e1a0'
down_revision = 'a63e90b72d14'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('vehicle_valuation_history',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('customer_id', sa.String(100), sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('vehicle_id', sa.String(36), sa.ForeignKey('vehicles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('state', sa.String(2), nullable=False),
        sa.Column('condition', sa.String(20), nullable=False),
        sa.Column('mileage', sa.Integer(), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_vehicle_valuation_history_customer_id', 'vehicle_valuation_history', ['customer_id'])
    op.create_index('ix_vehicle_valuation_history_vehicle_id', 'vehicle_valuation_history', ['vehicle_id'])
    if op.get_bind().dialect.name == 'postgresql':
        table = 'vehicle_valuation_history'
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON "{table}" FROM PUBLIC')
        for role in ('anon', 'authenticated'):
            op.execute(sa.text(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON {table} FROM {role}; END IF; END $$"))


def downgrade():
    op.drop_table('vehicle_valuation_history')
