"""Sintesi alert per la console di amministrazione.

Nota: la lavorazione investigativa (triage, dossier, network analysis,
disposizione) avviene in SAS Visual Investigator, non qui. Questo endpoint
espone solo una vista di sintesi/monitoraggio per gli amministratori.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas import Alert

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts() -> list[Alert]:
    # Placeholder: in produzione legge da PostgreSQL (sistema di record).
    return [
        Alert(
            id="a-0001",
            subject="ACME Costruzioni S.r.l.",
            cf_piva="01234567890",
            cup=["E51B21000000001"],
            ami_score=82,
            risk_level="ALTO",
            disposition="ESCALATION_I_LIVELLO",
            svi_alert_id="svi-0001",
            created_at=datetime.now(timezone.utc),
        )
    ]
