"""Private customer calendar bindings; OAuth credentials remain with Nango."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base, now, uid


class CalendarConnection(Base):
    __tablename__ = "customer_calendar_connections"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="disconnected")
    nango_connection_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    integration_id: Mapped[str] = mapped_column(String(100))
    environment: Mapped[str] = mapped_column(String(30))
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    selected_calendar_ids: Mapped[list] = mapped_column(JSON, default=list)
    time_zone: Mapped[str] = mapped_column(String(100), default="Etc/UTC")
    sync_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class CalendarAttempt(Base):
    __tablename__ = "customer_calendar_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    integration_id: Mapped[str] = mapped_column(String(100))
    environment: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    nango_connection_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    revoke_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    revoke_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_revoke_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class CalendarProvision(Base):
    __tablename__ = "customer_calendar_provisions"
    __table_args__ = (UniqueConstraint("customer_id", "nango_connection_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    nango_connection_id: Mapped[str] = mapped_column(String(200))
    nonce: Mapped[str] = mapped_column(String(36), default=uid)
    calendar_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CalendarOperation(Base):
    __tablename__ = "customer_calendar_operations"
    __table_args__ = (UniqueConstraint("customer_id", "source_kind", "source_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    source_kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(36))
    generation: Mapped[int] = mapped_column(Integer)
    nango_connection_id: Mapped[str] = mapped_column(String(200))
    calendar_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    event_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    applied_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(20), default="upsert")
    state: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
