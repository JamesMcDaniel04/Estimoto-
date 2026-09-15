"""Private customer Gmail bindings and scanned car-service mail metadata."""
from alembic import op
import sqlalchemy as sa

revision = 'b7e2d9c4a1f6'
down_revision = 'a4c1e7b9d2f3'
branch_labels = None
depends_on = None

TABLES = ('customer_gmail_connections', 'customer_gmail_attempts', 'customer_gmail_messages')


def customer(primary=False):
    return sa.Column('customer_id', sa.String(100), sa.ForeignKey('customers.id'), primary_key=primary, nullable=False)


def field(name, type_, nullable=False, primary_key=False):
    return sa.Column(name, type_, nullable=nullable, primary_key=primary_key)


def upgrade():
    op.create_table(TABLES[0], customer(True),
        field('generation', sa.Integer()), field('status', sa.String(30)),
        field('nango_connection_id', sa.String(200), True), field('integration_id', sa.String(100)),
        field('environment', sa.String(30)), field('attempt_id', sa.String(36), True),
        field('email_address', sa.String(320), True), field('last_scan_at', sa.DateTime(timezone=True), True))
    op.create_table(TABLES[1], field('id', sa.String(36), primary_key=True), customer(),
        field('generation', sa.Integer()), field('integration_id', sa.String(100)), field('environment', sa.String(30)),
        field('expires_at', sa.DateTime(timezone=True)), field('status', sa.String(30)),
        field('nango_connection_id', sa.String(200), True), field('revoke_pending', sa.Boolean()),
        field('revoke_attempts', sa.Integer()), field('next_revoke_at', sa.DateTime(timezone=True)))
    op.create_table(TABLES[2], field('id', sa.String(36), primary_key=True), customer(),
        field('generation', sa.Integer()), field('message_id', sa.String(64)), field('thread_id', sa.String(64)),
        field('received_at', sa.DateTime(timezone=True)), field('sender_name', sa.String(200)),
        field('sender_address', sa.String(320)), field('subject', sa.String(300)), field('snippet', sa.String(300)),
        field('category', sa.String(20)), field('status', sa.String(20)), field('knowledge_record_id', sa.String(36), True),
        field('created_at', sa.DateTime(timezone=True)), sa.UniqueConstraint('customer_id', 'message_id'))
    op.create_index('ix_customer_gmail_attempts_next_revoke_at', TABLES[1], ['next_revoke_at'])
    for table in TABLES[1:]:
        op.create_index('ix_' + table + '_customer_id', table, ['customer_id'])
    if op.get_bind().dialect.name == 'postgresql':
        for table in TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade():
    for table in reversed(TABLES):
        op.drop_table(table)
