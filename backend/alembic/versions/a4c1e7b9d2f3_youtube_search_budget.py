"""Daily budget for YouTube Data API searches behind Estibot care topics."""
from alembic import op
import sqlalchemy as sa

revision = 'a4c1e7b9d2f3'
down_revision = 'd9e4b82013c7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('youtube_search_budget',
                    sa.Column('day', sa.String(length=10), primary_key=True),
                    sa.Column('requests', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_table('youtube_search_budget')
