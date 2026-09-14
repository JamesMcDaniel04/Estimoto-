"""Shared Google Places request budget, without storing provider content."""
from alembic import op
import sqlalchemy as sa

revision = 'c8d3a7f102b6'
down_revision = 'b7f2c9d4e1a0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('places_request_budgets', sa.Column('day', sa.String(10), primary_key=True),
                    sa.Column('requests', sa.Integer(), nullable=False))
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE places_request_budgets ENABLE ROW LEVEL SECURITY')
        op.execute('REVOKE ALL ON places_request_budgets FROM PUBLIC')
        for role in ('anon', 'authenticated'):
            op.execute(sa.text(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON places_request_budgets FROM {role}; END IF; END $$"))


def downgrade():
    op.drop_table('places_request_budgets')
