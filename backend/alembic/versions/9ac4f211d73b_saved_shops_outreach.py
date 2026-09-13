"""Private saved shops and explicitly authorized email outbox.

Revision ID: 9ac4f211d73b
Revises: b9102d7e4c6f
"""
from alembic import op
import sqlalchemy as sa

revision = "9ac4f211d73b"
down_revision = "b9102d7e4c6f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("providers") as batch:
        batch.alter_column("city", existing_type=sa.String(100), type_=sa.String(120), existing_nullable=False)
    op.create_table("my_shops",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("vehicle_id", sa.String(36), sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(50), nullable=False),
        sa.Column("address", sa.String(300), nullable=False),
        sa.Column("website", sa.String(300), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_my_shops_customer_id", "my_shops", ["customer_id"])
    op.create_table("shop_outreach",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("shop_id", sa.String(36), sa.ForeignKey("my_shops.id"), nullable=False),
        sa.Column("vehicle_id", sa.String(36), sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("creation_key", sa.String(200), nullable=False),
        sa.Column("creation_hash", sa.String(64), nullable=False),
        sa.Column("review_hash", sa.String(64), nullable=False),
        sa.Column("shop_name", sa.String(200), nullable=False),
        sa.Column("recipient_email", sa.String(200), nullable=False),
        sa.Column("recipient_phone", sa.String(50), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("shared_contact", sa.JSON(), nullable=False),
        sa.Column("vehicle_summary", sa.String(300), nullable=False),
        sa.Column("proposed_slots", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("delivery_status", sa.String(30), nullable=False),
        sa.Column("authorized_key", sa.String(200), nullable=True),
        sa.Column("authorized_hash", sa.String(64), nullable=True),
        sa.Column("action_token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("action_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_slot", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", "creation_key"),
    )
    op.create_index("ix_shop_outreach_customer_id", "shop_outreach", ["customer_id"])
    op.create_table("shop_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("outreach_id", sa.String(36), sa.ForeignKey("shop_outreach.id"), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("first_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_id", sa.String(200), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_shop_outbox_due", "shop_outbox", ["next_attempt_at"])
    if op.get_bind().dialect.name == "postgresql":
        for table in ("my_shops", "shop_outreach", "shop_outbox"):
            op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        for role in ("anon", "authenticated"):
            op.execute(sa.text(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
                               f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}; "
                               "END IF; END $$"))


def downgrade():
    op.drop_index("ix_shop_outbox_due", table_name="shop_outbox")
    op.drop_table("shop_outbox")
    op.drop_index("ix_shop_outreach_customer_id", table_name="shop_outreach")
    op.drop_table("shop_outreach")
    op.drop_index("ix_my_shops_customer_id", table_name="my_shops")
    op.drop_table("my_shops")
    with op.batch_alter_table("providers") as batch:
        batch.alter_column("city", existing_type=sa.String(120), type_=sa.String(100), existing_nullable=False)
