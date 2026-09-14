"""Private customer Google Calendar bindings and durable appointment copies."""
from alembic import op
import sqlalchemy as sa

revision = "6db7a239f1c8"
down_revision = "e21870f6a94b"
branch_labels = None
depends_on = None

TABLES = ('customer_calendar_connections', 'customer_calendar_attempts',
          'customer_calendar_provisions', 'customer_calendar_operations')


def customer(primary=False):
    return sa.Column('customer_id', sa.String(100), sa.ForeignKey('customers.id'), primary_key=primary, nullable=False)


def field(name, type_, nullable=False, primary_key=False):
    return sa.Column(name, type_, nullable=nullable, primary_key=primary_key)


def upgrade():
    op.create_table(TABLES[0], customer(True),
        field('generation', sa.Integer()), field('status', sa.String(30)),
        field('nango_connection_id', sa.String(200), True), field('integration_id', sa.String(100)),
        field('environment', sa.String(30)), field('attempt_id', sa.String(36), True),
        field('selected_calendar_ids', sa.JSON()), field('time_zone', sa.String(100)), field('sync_confirmed', sa.Boolean()))
    op.create_table(TABLES[1], field('id', sa.String(36), primary_key=True), customer(),
        field('generation', sa.Integer()), field('integration_id', sa.String(100)), field('environment', sa.String(30)),
        field('expires_at', sa.DateTime(timezone=True)), field('status', sa.String(30)),
        field('nango_connection_id', sa.String(200), True), field('revoke_pending', sa.Boolean()), field('revoke_attempts', sa.Integer()), field('next_revoke_at', sa.DateTime(timezone=True)))
    op.create_table(TABLES[2], field('id', sa.String(36), primary_key=True), customer(),
        field('nango_connection_id', sa.String(200)), field('nonce', sa.String(36)), field('calendar_id', sa.String(500), True),
        field('status', sa.String(30)), field('claim_token', sa.String(36), True), field('lease_until', sa.DateTime(timezone=True), True),
        sa.UniqueConstraint('customer_id', 'nango_connection_id'))
    op.create_table(TABLES[3], field('id', sa.String(36), primary_key=True), customer(),
        field('source_kind', sa.String(20)), field('source_id', sa.String(36)), field('generation', sa.Integer()),
        field('nango_connection_id', sa.String(200)), field('calendar_id', sa.String(500), True), field('event_id', sa.String(64)),
        field('payload', sa.JSON()), field('payload_hash', sa.String(64)), field('applied_hash', sa.String(64), True),
        field('action', sa.String(20)), field('state', sa.String(30)), field('attempts', sa.Integer()),
        field('next_attempt_at', sa.DateTime(timezone=True)), field('claim_token', sa.String(36), True),
        field('lease_until', sa.DateTime(timezone=True), True), sa.UniqueConstraint('customer_id', 'source_kind', 'source_id'))
    op.create_index('ix_customer_calendar_attempts_next_revoke_at', TABLES[1], ['next_revoke_at'])
    for table in TABLES[1:]:
        op.create_index('ix_' + table + '_customer_id', table, ['customer_id'])
    for table in ('service_requests', 'shop_outreach'):
        op.add_column(table, field('calendar_last_scan_at', sa.DateTime(timezone=True), True))
        op.create_index('ix_' + table + '_calendar_last_scan_at', table, ['calendar_last_scan_at'])
        op.add_column(table, sa.Column('calendar_check', sa.Boolean(), nullable=False, server_default=sa.false()))
        op.add_column(table, sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='60'))
        op.add_column(table, field('calendar_generation', sa.Integer(), True))
        op.add_column(table, sa.Column('calendar_selected_ids', sa.JSON(), nullable=False, server_default='[]'))
        op.add_column(table, field('calendar_time_zone', sa.String(100), True))
        op.add_column(table, sa.Column('calendar_sync_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        op.add_column(table, sa.Column('calendar_sync_status', sa.String(30), nullable=False, server_default='not_enabled'))
        op.add_column(table, field('calendar_sync_message', sa.String(300), True))
    op.add_column('service_requests', sa.Column('proposed_slots', sa.JSON(), nullable=False, server_default='[]'))
    if op.get_bind().dialect.name == 'postgresql':
        for table in TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            for role in ('anon', 'authenticated', 'PUBLIC'):
                condition = 'TRUE' if role == 'PUBLIC' else f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')"
                op.execute(sa.text(f'DO $$ BEGIN IF {condition} THEN REVOKE ALL ON "{table}" FROM {role}; END IF; END $$'))


def downgrade():
    for table in ('service_requests', 'shop_outreach'):
        op.drop_index('ix_' + table + '_calendar_last_scan_at', table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column('calendar_last_scan_at')
            for name in ('calendar_check', 'duration_minutes', 'calendar_generation', 'calendar_selected_ids',
                         'calendar_time_zone', 'calendar_sync_enabled', 'calendar_sync_status', 'calendar_sync_message'):
                batch.drop_column(name)
            if table == 'service_requests':
                batch.drop_column('proposed_slots')
    for table in reversed(TABLES):
        op.drop_table(table)
