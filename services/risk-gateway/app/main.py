"""risk-gateway: feed di rischio strutturato (AML/CFT) per un soggetto risolto.

Punto unico di egress verso provider di dati di rischio esterni (oggi:
**Crime&tech**), analogo a `search-gateway`/`llm-gateway`. Il workflow lo invoca
**dopo** l'Entity Resolution: sul soggetto già disambiguato recupera indicatori
di rischio e connessioni, li mappa su categorie FATF/severità (AMI) ed evidenza
strutturata.

**Default OFF** (`RISK_PROVIDER` vuoto): risponde `available:false` e non esce
sulla rete. Attivazione solo con provider configurato; per Crime&tech serve
chiave + spec + ok compliance (DPA/DPIA), perché si invia identità reale (le PII
non si possono redigere: è una ricerca per identità).
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app import providers
from app.config import settings

app = FastAPI(title="Risk Gateway — Feed di rischio (AML/CFT)", version="0.1.0")


class SubjectIn(BaseModel):
    tipo_soggetto: str = "persona_giuridica"
    denominazione: str | None = None
    nome: str | None = None
    cognome: str | None = None
    data_nascita: str | None = None
    luogo_nascita: str | None = None
    cf_piva: str | None = None


class RiskRequest(BaseModel):
    subject: SubjectIn
    # entity_id già noto (se una fase a monte ha riconciliato il soggetto nel
    # dataset del provider); altrimenti la riconciliazione è demandata al client.
    entity_id: str | None = None


class RiskEvidence(BaseModel):
    tipo: str
    provider: str
    entity: str | None = None
    entity_id: str | None = None
    relationship: str | None = None
    crime_type: str | None = None
    fatf_category: str | None = None


class RiskResponse(BaseModel):
    provider: str
    available: bool
    reason: str | None = None
    entity_id: str | None = None
    fatf_categories: list[str] = []
    severity: str | None = None
    risk_indicators: list[dict] = []
    connections: list[dict] = []
    drivers: list[str] = []
    evidence: list[RiskEvidence] = []


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "provider": settings.risk_provider or None}


@app.get("/v1/providers")
def providers_status() -> dict:
    """Stato del feed di rischio (per introspezione / pagina Fonti)."""
    return providers.status()


@app.post("/v1/risk", response_model=RiskResponse)
def risk(req: RiskRequest) -> dict:
    """Assessment di rischio per il soggetto (feed strutturato). Non fatale:
    se il feed è OFF/non riconciliato/errore ritorna `available:false`."""
    return providers.assess(req.subject.model_dump())
