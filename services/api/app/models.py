"""Modelli ORM (SQLAlchemy 2.0). Postgres come sistema di record."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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


class Subject(Base):
    """Soggetto noto del registro anti-omonimia (§8): beneficiari/attuatori e
    relativi UBO/RUP/rappresentanti. In produzione sincronizzato da
    ReGiS/OpenCoesione/InfoCamere; qui gestibile anche dalla console."""

    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tipo_soggetto: Mapped[str] = mapped_column(String, default="persona_giuridica")
    denominazione: Mapped[str] = mapped_column(String)  # "Cognome Nome" per persona fisica
    cf_piva: Mapped[str | None] = mapped_column(String, nullable=True)
    data_nascita: Mapped[str | None] = mapped_column(String, nullable=True)
    luogo_nascita: Mapped[str | None] = mapped_column(String, nullable=True)
    cup: Mapped[list] = mapped_column(JSON, default=list)
    ruolo: Mapped[str | None] = mapped_column(String, nullable=True)
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Nomi simili già decisi da un revisore (alias / soggetti diversi): Entity Resolution.
    names: Mapped[list["SubjectName"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="SubjectName.decided_at"
    )


class SubjectName(Base):
    """Decisione di un revisore su un nome simile a quello di un soggetto del registro:
    «stesso» = variante dello stesso soggetto (refuso, ordine, nome precedente) → alias
    per l'Entity Resolution; «diverso» = altro soggetto, da non confondere né riproporre."""

    __tablename__ = "subject_names"
    __table_args__ = (UniqueConstraint("subject_id", "name_key", name="uq_subject_names_subject_key"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String)
    name_key: Mapped[str] = mapped_column(String)      # app.names.subject_key
    decision: Mapped[str] = mapped_column(String)      # stesso | diverso
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SubjectArticle(Base):
    """Articolo confermato da un revisore per un soggetto del registro, a valle
    dell'etichettatura: se lo riguarda e se è avverso, con il giudizio sul caso.
    È lo storico verificato del soggetto (sopravvive alla cancellazione dell'alert)."""

    __tablename__ = "subject_articles"
    __table_args__ = (UniqueConstraint("subject_id", "url", name="uq_subject_articles_subject_url"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    alert_id: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String)
    testata: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    data: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    pertinenza: Mapped[str] = mapped_column(String)
    avversa: Mapped[str] = mapped_column(String)
    categorie: Mapped[list] = mapped_column(JSON, default=list)
    ruolo: Mapped[str | None] = mapped_column(String, nullable=True)
    esito: Mapped[str | None] = mapped_column(String, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    confirmed_by_name: Mapped[str | None] = mapped_column(String, nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    """Operazioni sensibili (cancellazioni, correzioni del registro, conferme): chi,
    quando, cosa. I dettagli non ripetono dati personali oltre agli identificativi."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Screening(Base):
    __tablename__ = "screenings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    denominazione: Mapped[str] = mapped_column(String)
    tipo_soggetto: Mapped[str] = mapped_column(String, default="persona_giuridica")
    cf_piva: Mapped[str | None] = mapped_column(String, nullable=True)
    cup: Mapped[list] = mapped_column(JSON, default=list)
    seed_url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")  # running|completed|failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)   # motivo, se failed
    alert_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Alert(Base):
    __tablename__ = "alerts"

    # Un solo alert per screening: la persistenza dal worker è idempotente (0005).
    __table_args__ = (UniqueConstraint("screening_id", name="uq_alerts_screening_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    screening_id: Mapped[str | None] = mapped_column(ForeignKey("screenings.id"), nullable=True)
    subject: Mapped[str] = mapped_column(String)
    tipo_soggetto: Mapped[str] = mapped_column(String, default="persona_giuridica")
    cf_piva: Mapped[str | None] = mapped_column(String, nullable=True)
    cup: Mapped[list] = mapped_column(JSON, default=list)
    ami_score: Mapped[int] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String)
    fatf_categories: Mapped[list] = mapped_column(JSON, default=list)
    drivers: Mapped[list] = mapped_column(JSON, default=list)
    disposition: Mapped[str] = mapped_column(String)
    svi_alert_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Esito della pubblicazione in SVI, tracciato separatamente: l'alert è salvato
    # PRIMA di pubblicare, quindi un guasto SVI non fa perdere il risultato.
    # pending | published | failed | skipped (non pubblicato per scelta, es. ER non superata)
    svi_status: Mapped[str] = mapped_column(String, default="pending", server_default="pending")
    svi_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_resolution: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Predizione del classificatore (metodo llm/keyword, severità, ruolo, …): serve a
    # confrontare il sistema con le etichette dei revisori (dataset di valutazione).
    classification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Varianti vicine al nome citate negli articoli che NON citano il nome esatto
    # («Andrea Stroppa» per «Stropp Andrea»): possibile refuso nel nome del soggetto.
    name_variants: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Ordine stabile (di inserimento, id a parità): la numerazione in console
    # ("articolo 2") e quella dei messaggi dell'API coincidono.
    evidence: Mapped[list["Evidence"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin",
        order_by=lambda: (Evidence.created_at, Evidence.id),
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
    # Predizione del sistema su questo articolo: il soggetto è citato? (e come:
    # cf_piva / nome_cognome / denominazione / denominazione_breve).
    mentioned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mention_match: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CaseLabel(Base):
    """Etichetta di un revisore su un caso (alert), per il dataset di valutazione:
    per ogni articolo se riguarda davvero il soggetto e se è avverso; per il caso le
    categorie FATF corrette, il ruolo del soggetto, la disposition attesa e se il caso
    è **affidabile** (da includere nel dataset). Una per alert e revisore."""

    __tablename__ = "case_labels"
    __table_args__ = (UniqueConstraint("alert_id", "reviewer", name="uq_case_labels_alert_reviewer"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    reviewer: Mapped[str] = mapped_column(String)                 # sub (Entra) o nome
    reviewer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_labels: Mapped[dict] = mapped_column(JSON, default=dict)   # {evidence_id: {...}}
    categorie_corrette: Mapped[list] = mapped_column(JSON, default=list)
    ruolo: Mapped[str | None] = mapped_column(String, nullable=True)
    disposition_attesa: Mapped[str | None] = mapped_column(String, nullable=True)
    affidabile: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
