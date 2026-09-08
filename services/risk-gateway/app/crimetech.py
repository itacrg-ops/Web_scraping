"""Client **stub** per Crime&tech (Transcrime / Università Cattolica).

Crime&tech espone indicatori di rischio AML/CFT validati (per tipo di reato,
con rating esplicabile) su entità e persone, riconciliazione delle entità e la
rete di **connessioni**. Endpoint documentato di riferimento:

    GET /dataset/{dataset_id}/risk-indicators/{entity_id}/connections

**Stato: STUB, spec non ancora acquisita.** Questo modulo NON chiama l'API in
modalità predefinita. Due guardie devono essere entrambe vere perché la rete
venga toccata:
    settings.crimetech_live is True   AND   settings.crimetech_api_key != ""
In assenza (default), `fetch()` ritorna `(None, reason)` senza alcun egress.

Inoltre la **riconciliazione** entità→`entity_id` richiede un endpoint del
provider di cui non abbiamo ancora l'OpenAPI: finché non è integrato, `fetch()`
si ferma qui (nessun `entity_id`, nessuna chiamata alle connessioni). I nomi dei
campi nelle funzioni di normalizzazione sono **provvisori** e vanno confermati
sullo schema ufficiale prima dell'attivazione.
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger("risk-gateway.crimetech")

# Template dell'endpoint documentato (connessioni + indicatori di rischio).
CONNECTIONS_PATH = "/dataset/{dataset_id}/risk-indicators/{entity_id}/connections"


def _live_enabled() -> tuple[bool, str]:
    """Guardia hard all'egress. Ritorna (abilitato, motivo-se-no)."""
    if not settings.crimetech_live:
        return False, "live disabilitato (CRIMETECH_LIVE=false): nessuna chiamata esterna"
    if not settings.crimetech_api_key:
        return False, "chiave assente (CRIMETECH_API_KEY vuota): nessuna chiamata esterna"
    if not settings.crimetech_dataset_id:
        return False, "dataset non configurato (CRIMETECH_DATASET_ID vuoto)"
    return True, ""


def _resolve_entity_id(subject: dict[str, Any]) -> str | None:
    """Riconciliazione soggetto → `entity_id` nel dataset del provider.

    Passo necessario prima delle connessioni: dai nostri identificatori
    (CF/P.IVA/denominazione) all'`entity_id` di Crime&tech. L'endpoint di
    reconcile NON è ancora integrato (spec mancante): ritorna None finché non
    lo colleghiamo. NON inventiamo un endpoint per non fare egress a caso.
    """
    logger.info("Crime&tech reconcile non integrato (spec mancante): soggetto non risolto")
    return None


def _normalize_connections_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Traduce la risposta grezza dell'endpoint /connections nella forma
    normalizzata attesa da `mapping.build_assessment`.

    **Provvisorio**: i nomi dei campi (`risk_indicators`, `connections`,
    `crime_type`, `rating`, ...) vanno confermati sull'OpenAPI ufficiale. È
    isolato qui apposta, così l'aggancio è l'unico punto da ritoccare a spec
    acquisita.
    """
    indicators = []
    for it in (payload.get("risk_indicators") or payload.get("indicators") or []):
        indicators.append({
            "indicator": it.get("name") or it.get("indicator"),
            "crime_type": it.get("crime_type") or it.get("category"),
            "rating": it.get("rating") or it.get("level") or it.get("risk"),
            "score": it.get("score"),
            "explanation": it.get("explanation") or it.get("description"),
        })
    connections = []
    for c in (payload.get("connections") or payload.get("edges") or []):
        connections.append({
            "entity": c.get("name") or c.get("entity") or c.get("target"),
            "entity_id": c.get("entity_id") or c.get("id"),
            "relationship": c.get("relationship") or c.get("role") or c.get("type"),
            "risk_flag": bool(c.get("risk_flag") or c.get("at_risk") or c.get("flagged")),
            "crime_type": c.get("crime_type") or c.get("category"),
            "rating": c.get("rating") or c.get("level"),
        })
    return {"entity_id": payload.get("entity_id"), "risk_indicators": indicators,
            "connections": connections}


def fetch(subject: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Recupera il profilo di rischio normalizzato per il soggetto.

    Ritorna `(raw_normalizzato, "")` in caso di successo oppure `(None, motivo)`
    quando il feed non è utilizzabile (stub/guardie/errore). NON solleva: il
    feed è **non fatale** per la pipeline.
    """
    ok, why = _live_enabled()
    if not ok:
        return None, f"stub: {why}"

    entity_id = _resolve_entity_id(subject)
    if not entity_id:
        return None, "entità non riconciliata (reconcile Crime&tech non ancora integrato)"

    # --- Ramo live (raggiungibile solo con guardie+reconcile soddisfatti) ---
    # Import lazy: httpx serve solo qui. L'egress verso api.crimetech.app è
    # oggi bloccato dal proxy dell'ambiente; questo ramo resta pronto per
    # l'attivazione a spec+chiave+ok compliance acquisiti.
    import httpx  # noqa: PLC0415 — import locale volutamente pigro

    url = settings.crimetech_base_url.rstrip("/") + CONNECTIONS_PATH.format(
        dataset_id=settings.crimetech_dataset_id, entity_id=entity_id)
    headers = {"Authorization": f"Bearer {settings.crimetech_api_key}",
               "Accept": "application/json"}
    try:
        resp = httpx.get(url, headers=headers, timeout=settings.request_timeout)
        resp.raise_for_status()
        return _normalize_connections_response(resp.json()), ""
    except Exception as exc:  # noqa: BLE001 — non fatale
        logger.warning("Crime&tech non raggiungibile (%s)", exc)
        return None, f"errore chiamata Crime&tech: {exc}"
