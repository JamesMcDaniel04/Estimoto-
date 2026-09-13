"""Private uploaded vehicle photos and bounded representative image cache.

Revision ID: e21870f6a94b
Revises: c54d09a2f173
"""
from alembic import op
import sqlalchemy as sa

revision = "e21870f6a94b"
down_revision = "c54d09a2f173"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("vehicles", sa.Column("image_storage_name", sa.String(36), nullable=True))
    op.add_column("vehicles", sa.Column("image_version", sa.String(64), nullable=True))
    op.add_column("vehicles", sa.Column("image_byte_size", sa.Integer(), nullable=True))
    op.create_table("vehicle_image_cache",
        sa.Column("cache_key", sa.String(64), primary_key=True),
        sa.Column("image_data", sa.LargeBinary(), nullable=True),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))
    op.create_table("vehicle_image_provider_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day_bucket", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        for table in ("vehicle_image_cache", "vehicle_image_provider_state"):
            op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
            for role in ("anon", "authenticated", "PUBLIC"):
                condition = "TRUE" if role == "PUBLIC" else f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')"
                op.execute(sa.text(f"DO $$ BEGIN IF {condition} THEN REVOKE ALL ON public.\"{table}\" FROM {role}; END IF; END $$"))


def downgrade():
    op.drop_table("vehicle_image_provider_state")
    op.drop_table("vehicle_image_cache")
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("image_byte_size")
        batch.drop_column("image_version")
        batch.drop_column("image_storage_name")
