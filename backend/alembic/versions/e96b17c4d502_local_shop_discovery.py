"""Public OSM cache, private dedicated shops and explicit visit admission."""
from alembic import op
import sqlalchemy as sa

revision = 'e96b17c4d502'
down_revision = '6db7a239f1c8'
branch_labels = None
depends_on = None
TABLES = ('public_directory_cache', 'public_directory_listings', 'customer_dedicated_shops', 'public_directory_budgets')


def upgrade():
    op.create_table(TABLES[0], sa.Column('key', sa.String(80), primary_key=True),
        sa.Column('value', sa.JSON(), nullable=False), sa.Column('fetched_at', sa.DateTime(timezone=True)),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('claim_token', sa.String(36)), sa.Column('lease_until', sa.DateTime(timezone=True)))
    op.create_index('ix_public_directory_cache_fetched_at', TABLES[0], ['fetched_at'])
    op.create_table(TABLES[1], sa.Column('source_id', sa.String(60), primary_key=True),
        sa.Column('value', sa.JSON(), nullable=False), sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_public_directory_listings_fetched_at', TABLES[1], ['fetched_at'])
    op.create_table(TABLES[2], sa.Column('customer_id', sa.String(100), sa.ForeignKey('customers.id'), primary_key=True),
        sa.Column('vehicle_id', sa.String(36), sa.ForeignKey('vehicles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('specialty', sa.String(30), primary_key=True), sa.Column('source', sa.String(30), nullable=False),
        sa.Column('source_id', sa.String(100), nullable=False))
    op.create_table(TABLES[3], sa.Column('day', sa.String(10), primary_key=True),
        sa.Column('attempts', sa.Integer(), nullable=False), sa.Column('body_bytes', sa.Integer(), nullable=False))
    for table in ('service_requests', 'estimates'):
        op.add_column(table, sa.Column('service_mode', sa.String(20)))
        op.add_column(table, sa.Column('discovery_admission', sa.JSON(), nullable=False, server_default='{}'))
    if op.get_bind().dialect.name == 'postgresql':
        for table in TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            for role in ('PUBLIC', 'anon', 'authenticated'):
                exists = 'TRUE' if role == 'PUBLIC' else f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')"
                op.execute(sa.text(f'DO $$ BEGIN IF {exists} THEN REVOKE ALL ON "{table}" FROM {role}; END IF; END $$'))


def downgrade():
    for table in ('service_requests', 'estimates'):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('service_mode')
            batch.drop_column('discovery_admission')
    for table in reversed(TABLES):
        op.drop_table(table)
