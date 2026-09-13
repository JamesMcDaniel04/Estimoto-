"""Durable submitted estimates and private evidence metadata.

Revision ID: b9102d7e4c6f
Revises: 79ae381cd042
"""
from alembic import op
import sqlalchemy as sa

revision = "b9102d7e4c6f"
down_revision = "79ae381cd042"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("service_requests", sa.Column("last_status_poll_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("estimates") as batch:
        batch.add_column(sa.Column("provider_id", sa.String(36), sa.ForeignKey("providers.id", name="fk_estimates_provider_id"), nullable=True))
        batch.add_column(sa.Column("submission_key", sa.String(200), nullable=True))
        batch.add_column(sa.Column("submission_request_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("delivery_status", sa.String(20), nullable=False, server_default="draft"))
        batch.add_column(sa.Column("processing_state", sa.String(20), nullable=False, server_default="not_started"))
        batch.add_column(sa.Column("processing_error", sa.String(500), nullable=True))
    op.add_column("photos", sa.Column("sha256", sa.String(64), nullable=True))
    op.add_column("photos", sa.Column("byte_size", sa.Integer(), nullable=True))
    op.create_table("estimate_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("estimate_id", sa.String(36), sa.ForeignKey("estimates.id"), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receipt_id", sa.String(200), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_estimate_outbox_due", "estimate_outbox", ["next_attempt_at"])
    op.create_table("rate_buckets",
        sa.Column("customer_id", sa.String(100), sa.ForeignKey("customers.id"), primary_key=True),
        sa.Column("action", sa.String(30), primary_key=True),
        sa.Column("hour_bucket", sa.Integer(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        # Supabase exposes public-schema tables via Data API roles unless access
        # is explicitly denied. The app connects as its table-owning DB role.
        for table in ("customers", "vehicles", "providers", "service_requests", "request_events",
                      "outbox", "request_rejections", "estimates", "estimate_outbox", "photos", "repairs", "reminders", "rate_buckets"):
            op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        for role in ("anon", "authenticated"):
            op.execute(sa.text(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
                               f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}; "
                               "END IF; END $$"))


def downgrade():
    op.drop_column("service_requests", "last_status_poll_at")
    op.drop_table("rate_buckets")
    op.drop_index("ix_estimate_outbox_due", table_name="estimate_outbox")
    op.drop_table("estimate_outbox")
    for column in ("byte_size", "sha256"):
        op.drop_column("photos", column)
    with op.batch_alter_table("estimates") as batch:
        for column in ("processing_error", "processing_state", "delivery_status", "submission_request_hash",
                       "submission_key", "provider_id"):
            batch.drop_column(column)
