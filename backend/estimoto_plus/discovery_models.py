"""Public ODbL cache and separately owned customer shop preferences."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base, now


class DirectoryCache(Base):
    __tablename__ = 'public_directory_cache'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublicListing(Base):
    __tablename__ = 'public_directory_listings'
    source_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class DedicatedShop(Base):
    __tablename__ = 'customer_dedicated_shops'
    customer_id: Mapped[str] = mapped_column(ForeignKey('customers.id'), primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('vehicles.id', ondelete='CASCADE'), primary_key=True)
    specialty: Mapped[str] = mapped_column(String(30), primary_key=True)
    source: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(100))


class DirectoryBudget(Base):
    __tablename__ = 'public_directory_budgets'
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    body_bytes: Mapped[int] = mapped_column(Integer, default=0)


class PlacesBudget(Base):
    """Counters only. Google content is never stored in the ODbL directory."""
    __tablename__ = 'places_request_budgets'
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
