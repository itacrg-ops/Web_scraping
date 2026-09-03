"""Pubblicazione in SAS Visual Investigator (Data Hub + Alerts API).

Anti-corruption layer: incapsula tutta la conoscenza specifica di SVI.
Se l'API SVI cambia, cambia solo questo modulo.

Modalità:
  - mock : logga e restituisce id fittizi (sviluppo locale senza Viya);
  - live : chiama le REST API SVI con Bearer token SASLogon (dal broker).
"""
from __future__ import annotations

import logging
import uuid

import httpx

from app.config import settings

logger = logging.getLogger("svi_publisher")


def _is_mock() -> bool:
    return settings.svi_mode.lower() != "live"


async def _bearer() -> str:
    """Ottiene un token SASLogon di servizio dal sas-token-broker (sidecar)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(settings.sas_token_broker_url)
        resp.raise_for_status()
        return resp.json()["access_token"]


async def publish_entities(entities: list[dict], relationships: list[dict]) -> None:
    """Carica entità/relazioni nel modello dati SVI (Data Hub API)."""
    if _is_mock():
        logger.info("[MOCK] Data Hub: %d entità, %d relazioni", len(entities), len(relationships))
        return
    token = await _bearer()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=settings.svi_datahub_base, headers=headers, timeout=30) as c:
        # TODO: mappare sugli endpoint reali del Data Hub (entity types e relazioni).
        await c.post("/entities", json={"entities": entities, "relationships": relationships})


async def publish_alert(alert: dict) -> str:
    """Crea un alert in SVI (Alerts API) e lo instrada alla coda del I livello."""
    if _is_mock():
        alert_id = f"svi-mock-{uuid.uuid4().hex[:8]}"
        logger.info("[MOCK] Alert creato: %s (subject=%s, ami=%s)",
                    alert_id, alert.get("subject"), alert.get("ami_score"))
        return alert_id
    token = await _bearer()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=settings.svi_alerts_base, headers=headers, timeout=30) as c:
        # TODO: adattare al payload reale dell'Alerts API SVI.
        resp = await c.post("/alerts", json=alert)
        resp.raise_for_status()
        return resp.json().get("id", "")
