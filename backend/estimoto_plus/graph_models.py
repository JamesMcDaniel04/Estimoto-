"""Customer-owned graph with explicit evidence and optional aggregate use."""
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from .models import Base, uid, now


class KnowledgePreference(Base):
    __tablename__ = "knowledge_preferences"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), primary_key=True)
    share_aggregate_insights: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_version: Mapped[str] = mapped_column(String(30), default="2026-09-13")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KnowledgeRecord(Base):
    __tablename__ = "knowledge_records"
    __table_args__ = (UniqueConstraint("customer_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"), index=True)
    service_type: Mapped[str] = mapped_column(String(30))
    service_date: Mapped[str] = mapped_column(String(10))
    mileage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shop_name: Mapped[str] = mapped_column(String(200), default="")
    parts_source: Mapped[str] = mapped_column(String(200), default="")
    parts_description: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(String(1000), default="")
    source: Mapped[str] = mapped_column(String(30), default="customer_reported")
    idempotency_key: Mapped[str] = mapped_column(String(200))
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KnowledgeDeletion(Base):
    __tablename__ = "knowledge_deletions"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KnowledgeConsentEvent(Base):
    __tablename__ = "knowledge_consent_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    share_aggregate_insights: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GraphEntity(Base):
    __tablename__ = "graph_entities"
    __table_args__ = (UniqueConstraint("customer_id", "kind", "source_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    source_key: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(200))
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (UniqueConstraint("record_id", "from_id", "relation", "to_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("knowledge_records.id"), index=True)
    from_id: Mapped[str] = mapped_column(ForeignKey("graph_entities.id"))
    to_id: Mapped[str] = mapped_column(ForeignKey("graph_entities.id"))
    relation: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(30), default="customer_reported")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
