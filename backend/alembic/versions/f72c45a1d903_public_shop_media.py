"""Source-verified public shop media.

Revision ID: f72c45a1d903
Revises: 32ac7f618b90
"""
from alembic import op
import sqlalchemy as sa

revision = 'f72c45a1d903'
down_revision = '32ac7f618b90'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('providers', sa.Column('media', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('providers', 'media')
