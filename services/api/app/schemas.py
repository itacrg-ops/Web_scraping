"""Schemi Pydantic esposti dall'API (contratto per la console React)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Source(BaseModel):
    """Voce del registro fonti (§5.1 del capitolato)."""

    id: str
    nome: str
    tipo: str = Field(description="feed | api | scraping")
    credibilita: str = Field(description="alta | media | bassa")
    rischio_legale: str = Field(description="basso | medio | alto")
    crawl_delay_s: float = 2.0
    respect_robots: bool = True
    attiva: bool = True


class Alert(BaseModel):
    """Sintesi dell'alert (il dettaglio investigativo vive in SAS Visual Investigator)."""

    id: str
    subject: str
    cf_piva: str | None = None
    cup: list[str] = []
    ami_score: int
    risk_level: str
    disposition: str
    svi_alert_id: str | None = None
    created_at: datetime
