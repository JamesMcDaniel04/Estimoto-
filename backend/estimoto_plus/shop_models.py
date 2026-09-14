"""Private customer shops, immutable outreach reviews, and durable email delivery."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, CalendarSourceMixin, now, uid


class MyShop(Base):
    __tablename__ = "my_shops"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    website: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ShopOutreach(CalendarSourceMixin, Base):
    __tablename__ = "shop_outreach"
    __table_args__ = (UniqueConstraint("customer_id", "creation_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("my_shops.id"))
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    creation_key: Mapped[str] = mapped_column(String(200))
    creation_hash: Mapped[str] = mapped_column(String(64))
    review_hash: Mapped[str] = mapped_column(String(64))
    shop_name: Mapped[str] = mapped_column(String(200))
    recipient_email: Mapped[str] = mapped_column(String(200), default="")
    recipient_phone: Mapped[str] = mapped_column(String(50), default="")
    subject: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text)
    shared_contact: Mapped[dict] = mapped_column(JSON)
    vehicle_summary: Mapped[str] = mapped_column(String(300), default="")
    proposed_slots: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    delivery_status: Mapped[str] = mapped_column(String(30), default="draft")
    authorized_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    authorized_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    action_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_slot: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ShopOutbox(Base):
    __tablename__ = "shop_outbox"
    __table_args__ = (Index("ix_shop_outbox_due", "next_attempt_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    outreach_id: Mapped[str] = mapped_column(ForeignKey("shop_outreach.id"), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    first_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
