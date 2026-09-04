"""Schemi Pydantic esposti dall'API (contratto per console e worker)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Source(BaseModel):
    """Voce del registro fonti (§5.1)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    nome: str
    tipo: str = Field(description="feed | api | scraping")
    credibilita: str
    rischio_legale: str
    crawl_delay_s: float = 2.0
    respect_robots: bool = True
    attiva: bool = True


class ScreeningRequest(BaseModel):
    """Richiesta di avvio screening (dalla console)."""

    denominazione: str
    cf_piva: str | None = None
    cup: list[str] = []
    seed_url: str | None = None


class ScreeningOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    denominazione: str
    status: str
    alert_id: str | None = None
    created_at: datetime


class AlertCreate(BaseModel):
    """Payload di persistenza alert (chiamato dal worker a fine pipeline)."""

    screening_id: str | None = None
    subject: str
    cf_piva: str | None = None
    cup: list[str] = []
    ami_score: int
    risk_level: str
    fatf_categories: list[str] = []
    drivers: list[str] = []
    disposition: str = "ESCALATION_I_LIVELLO"
    svi_alert_id: str | None = None
    entity_resolution: dict | None = None


class Alert(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    screening_id: str | None = None
    subject: str
    cf_piva: str | None = None
    cup: list[str] = []
    ami_score: int
    risk_level: str
    fatf_categories: list[str] = []
    drivers: list[str] = []
    disposition: str
    svi_alert_id: str | None = None
    entity_resolution: dict | None = None
    created_at: datetime
