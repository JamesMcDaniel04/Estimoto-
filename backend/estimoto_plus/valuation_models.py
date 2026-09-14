"""Private, bounded valuation cache; never store credentials or raw provider input."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base, now, uid


class VehicleValuationCache(Base):
    __tablename__ = 'vehicle_valuation_cache'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('vehicles.id', ondelete='CASCADE'), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey('customers.id', ondelete='CASCADE'), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ValuationProviderState(Base):
    __tablename__ = 'valuation_provider_state'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day_bucket: Mapped[int] = mapped_column(Integer, default=0)
    count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VehicleValuationHistory(Base):
    """Every successful lookup the customer ran, newest first, capped per vehicle."""
    __tablename__ = 'vehicle_valuation_history'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey('customers.id', ondelete='CASCADE'), index=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('vehicles.id', ondelete='CASCADE'), index=True)
    state: Mapped[str] = mapped_column(String(2))
    condition: Mapped[str] = mapped_column(String(20))
    mileage: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
