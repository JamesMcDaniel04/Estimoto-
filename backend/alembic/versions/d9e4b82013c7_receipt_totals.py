"""Private receipt total extraction, retained with the attachment."""
from alembic import op
import sqlalchemy as sa

revision = 'd9e4b82013c7'
down_revision = 'c8d3a7f102b6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('knowledge_receipts', sa.Column('total_extraction', sa.JSON(), nullable=False, server_default='{}'))


def downgrade():
    with op.batch_alter_table('knowledge_receipts') as batch:
        batch.drop_column('total_extraction')
