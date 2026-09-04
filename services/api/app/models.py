"""Modelli ORM (SQLAlchemy 2.0). Postgres come sistema di record."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nome: Mapped[str] = mapped_column(String)
    tipo: Mapped[str] = mapped_column(String)
    credibilita: Mapped[str] = mapped_column(String)
    rischio_legale: Mapped[str] = mapped_column(String)
    crawl_delay_s: Mapped[float] = mapped_column(Float, default=2.0)
    respect_robots: Mapped[bool] = mapped_column(Boolean, default=True)
    attiva: Mapped[bool] = mapped_column(Boolean, default=True)


class Screening(Base):
    __tablename__ = "screenings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    denominazione: Mapped[str] = mapped_column(String)
    cf_piva: Mapped[str | None] = mapped_column(String, nullable=True)
    cup: Mapped[list] = mapped_column(JSON, default=list)
    seed_url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")  # running|completed|failed
    alert_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    screening_id: Mapped[str | None] = mapped_column(ForeignKey("screenings.id"), nullable=True)
    subject: Mapped[str] = mapped_column(String)
    cf_piva: Mapped[str | None] = mapped_column(String, nullable=True)
    cup: Mapped[list] = mapped_column(JSON, default=list)
    ami_score: Mapped[int] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String)
    fatf_categories: Mapped[list] = mapped_column(JSON, default=list)
    drivers: Mapped[list] = mapped_column(JSON, default=list)
    disposition: Mapped[str] = mapped_column(String)
    svi_alert_id: Mapped[str | None] = mapped_column(String, nullable=True)
    entity_resolution: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    evidence: Mapped[list["Evidence"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class Evidence(Base):
    """Evidenza ancorata all'alert (§7.1): URL, testata, data, snippet, hash,
    provenance (WARC), timestamp — base della spiegabilità dell'alert."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"))
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    testata: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    data: Mapped[str | None] = mapped_column(String, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    fetch_ts: Mapped[str | None] = mapped_column(String, nullable=True)
    bucket: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_key: Mapped[str | None] = mapped_column(String, nullable=True)
    warc_key: Mapped[str | None] = mapped_column(String, nullable=True)
    fonte_credibilita: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
