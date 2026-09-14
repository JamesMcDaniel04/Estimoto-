"""Private capture receipts and VIN suggestions, separate from learning data."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base, now


class CaptureReceipt(Base):
    __tablename__ = 'customer_capture_receipts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey('customers.id'), index=True)
    estimate_id: Mapped[str] = mapped_column(ForeignKey('estimates.id'), index=True)
    capture_key: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default='pending')
    claim_token: Mapped[str] = mapped_column(String(36))
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    replaced_storage: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CaptureVinSuggestion(Base):
    __tablename__ = 'customer_capture_vin_suggestions'
    photo_id: Mapped[str] = mapped_column(ForeignKey('photos.id'), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey('customers.id'), index=True)
    estimate_id: Mapped[str] = mapped_column(ForeignKey('estimates.id'), index=True)
    photo_sha256: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
