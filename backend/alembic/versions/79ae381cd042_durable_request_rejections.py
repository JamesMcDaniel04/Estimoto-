"""Persist terminal request rejections across delayed retries.

Revision ID: 79ae381cd042
Revises: d752dbef8104
"""
from alembic import op
import sqlalchemy as sa

revision = '79ae381cd042'
down_revision = 'd752dbef8104'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('request_rejections',
        sa.Column('customer_id', sa.String(100), sa.ForeignKey('customers.id'), primary_key=True),
        sa.Column('idempotency_key', sa.String(200), primary_key=True),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('detail', sa.String(200), nullable=False),
        sa.Column('code', sa.String(40), nullable=False),
    )


def downgrade():
    op.drop_table('request_rejections')
