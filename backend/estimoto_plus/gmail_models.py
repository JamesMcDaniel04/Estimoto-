"""Private customer Gmail bindings; OAuth credentials remain with Nango.

Only message metadata the customer chose to scan for (sender, subject, date,
category and Gmail's short snippet) is stored. Message bodies and attachments
are never fetched.
"""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base, now, uid


class GmailConnection(Base):
    __tablename__ = "customer_gmail_connections"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="disconnected")
    nango_connection_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    integration_id: Mapped[str] = mapped_column(String(100))
    environment: Mapped[str] = mapped_column(String(30))
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    email_address: Mapped[str | None] = mapped_column(String(320), nullable=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GmailAttempt(Base):
    __tablename__ = "customer_gmail_attempts"
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


class GmailMessage(Base):
    __tablename__ = "customer_gmail_messages"
    __table_args__ = (UniqueConstraint("customer_id", "message_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[str] = mapped_column(String(64))
    thread_id: Mapped[str] = mapped_column(String(64), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sender_name: Mapped[str] = mapped_column(String(200), default="")
    sender_address: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(String(300), default="")
    snippet: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(20), default="service")
    status: Mapped[str] = mapped_column(String(20), default="new")
    knowledge_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
