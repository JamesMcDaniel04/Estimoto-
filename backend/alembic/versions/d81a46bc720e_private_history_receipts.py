"""Private history receipt evidence and recorded costs.

Revision ID: d81a46bc720e
Revises: f72c45a1d903
"""
from alembic import op
import sqlalchemy as sa

revision = "d81a46bc720e"
down_revision = "f72c45a1d903"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("knowledge_records", sa.Column("cost_cents", sa.Integer(), nullable=True))
    op.create_table("knowledge_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("record_id", sa.String(36), sa.ForeignKey("knowledge_records.id"), nullable=True),
        sa.Column("idempotency_key", sa.String(36), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("storage_name", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("cleanup_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", "idempotency_key"))
    for column in ("customer_id", "record_id"):
        op.create_index(f"ix_knowledge_receipts_{column}", "knowledge_receipts", [column])
    if op.get_bind().dialect.name == "postgresql":
        op.execute('ALTER TABLE "knowledge_receipts" ENABLE ROW LEVEL SECURITY')
        op.execute('REVOKE ALL ON "knowledge_receipts" FROM PUBLIC')
        for role in ("anon", "authenticated"):
            op.execute(sa.text(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON knowledge_receipts FROM {role}; END IF; END $$"))


def downgrade():
    op.drop_table("knowledge_receipts")
    op.drop_column("knowledge_records", "cost_cents")
