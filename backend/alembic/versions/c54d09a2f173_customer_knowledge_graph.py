"""Customer repair history, source-linked graph and aggregate consent.

Revision ID: c54d09a2f173
Revises: 9ac4f211d73b
"""
from alembic import op
import sqlalchemy as sa

revision = "c54d09a2f173"
down_revision = "9ac4f211d73b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("knowledge_preferences",
        sa.Column("customer_id", sa.String(100), sa.ForeignKey("customers.id"), primary_key=True),
        sa.Column("share_aggregate_insights", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.String(30), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("knowledge_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("vehicle_id", sa.String(36), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("service_type", sa.String(30), nullable=False),
        sa.Column("service_date", sa.String(10), nullable=False),
        sa.Column("mileage", sa.Integer(), nullable=True),
        sa.Column("shop_name", sa.String(200), nullable=False),
        sa.Column("parts_source", sa.String(200), nullable=False),
        sa.Column("parts_description", sa.String(200), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", "idempotency_key"))
    op.create_index("ix_knowledge_records_customer_id", "knowledge_records", ["customer_id"])
    op.create_index("ix_knowledge_records_vehicle_id", "knowledge_records", ["vehicle_id"])
    op.create_table("knowledge_deletions",
        sa.Column("customer_id", sa.String(100), sa.ForeignKey("customers.id"), primary_key=True),
        sa.Column("idempotency_key", sa.String(200), primary_key=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("knowledge_consent_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("share_aggregate_insights", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_knowledge_consent_events_customer_id", "knowledge_consent_events", ["customer_id"])
    op.create_table("graph_entities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("source_key", sa.String(100), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.UniqueConstraint("customer_id", "kind", "source_key"))
    op.create_index("ix_graph_entities_customer_id", "graph_entities", ["customer_id"])
    op.create_table("graph_edges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("record_id", sa.String(36), sa.ForeignKey("knowledge_records.id"), nullable=False),
        sa.Column("from_id", sa.String(36), sa.ForeignKey("graph_entities.id"), nullable=False),
        sa.Column("to_id", sa.String(36), sa.ForeignKey("graph_entities.id"), nullable=False),
        sa.Column("relation", sa.String(40), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("record_id", "from_id", "relation", "to_id"))
    op.create_index("ix_graph_edges_customer_id", "graph_edges", ["customer_id"])
    op.create_index("ix_graph_edges_record_id", "graph_edges", ["record_id"])
    if op.get_bind().dialect.name == "postgresql":
        for table in ("knowledge_preferences", "knowledge_records", "knowledge_deletions",
                      "knowledge_consent_events", "graph_entities", "graph_edges"):
            op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
            for role in ("anon", "authenticated", "PUBLIC"):
                # Local PostgreSQL fixtures need not have Supabase's two roles.
                condition = "TRUE" if role == "PUBLIC" else f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')"
                op.execute(sa.text(f"DO $$ BEGIN IF {condition} THEN REVOKE ALL ON public.\"{table}\" FROM {role}; END IF; END $$"))


def downgrade():
    for table in ("graph_edges", "graph_entities", "knowledge_consent_events", "knowledge_deletions",
                  "knowledge_records", "knowledge_preferences"):
        op.drop_table(table)
