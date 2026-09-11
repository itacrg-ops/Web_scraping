"""Pubblicazione in SAS Visual Investigator (Data Hub + Alerts API).

Anti-corruption layer: incapsula tutta la conoscenza specifica di SVI. Se l'API
SVI cambia, cambia solo questo modulo (payload in `mapping.py`, auth in `auth.py`).

Modalità:
  - mock : logga e restituisce id deterministici (sviluppo locale senza Viya);
  - live : OAuth2/broker → crea il documento nel Data Hub → crea l'alert.

Robustezza: **retry con backoff** sugli errori transitori; **idempotenza** via
business key (stesso screening → stesso id, nessun duplicato su ripubblicazione).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

import httpx

from app import auth, mapping
from app.config import settings

logger = logging.getLogger("svi_publisher")

# Cache di idempotenza in-process: business_key -> (ts, svi_alert_id, document_id).
# In prod: outbox/Redis condiviso. Evita duplicati sui retry (Temporal) e sulle
# ripubblicazioni dello stesso screening.
_published: dict[str, tuple[float, str, str | None]] = {}

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_mock() -> bool:
    return settings.svi_mode.lower() != "live"


def _idem_get(key: str) -> tuple[str, str | None] | None:
    hit = _published.get(key)
    if hit and (time.time() - hit[0]) < settings.svi_idempotency_ttl:
        return hit[1], hit[2]
    return None


def _idem_put(key: str, alert_id: str, document_id: str | None) -> None:
    if len(_published) > 5000:
        _published.clear()
    _published[key] = (time.time(), alert_id, document_id)


async def _retry(desc: str, call: Callable[[], Any]) -> httpx.Response:
    """Esegue `call()` (coroutine factory) con retry+backoff su errori transitori
    (timeout/connessione/5xx/429). Rilancia l'ultimo errore se esauriti i tentativi."""
    last: Exception | None = None
    for attempt in range(settings.svi_max_retries + 1):
        try:
            resp = await call()
            if resp.status_code in _RETRYABLE_STATUS:
                raise httpx.HTTPStatusError(f"{resp.status_code}", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last = exc
            if attempt >= settings.svi_max_retries:
                break
            wait = settings.svi_retry_backoff * (2 ** attempt)
            logger.warning("SVI %s: tentativo %d fallito (%s), retry tra %.1fs",
                           desc, attempt + 1, exc, wait)
            await asyncio.sleep(wait)
    raise last if last else RuntimeError(f"SVI {desc}: fallito")


async def publish_alert(alert: dict[str, Any]) -> dict[str, Any]:
    """Crea un alert in SVI (documento Data Hub + alert) in modo idempotente.

    Ritorna {svi_alert_id, document_id, deduplicated}."""
    key = mapping.business_key(alert)
    cached = _idem_get(key)
    if cached is not None:
        logger.info("SVI alert già pubblicato (idempotenza) key=%s id=%s", key, cached[0])
        return {"svi_alert_id": cached[0], "document_id": cached[1], "deduplicated": True}

    if _is_mock():
        alert_id = f"svi-mock-{key.split('-')[-1][:8]}"
        doc_id = f"doc-mock-{key.split('-')[-1][:8]}"
        logger.info("[MOCK] Alert SVI creato: %s (subject=%s, ami=%s, evidenze=%d)",
                    alert_id, alert.get("subject"), alert.get("ami_score"),
                    len(alert.get("evidence") or []))
        _idem_put(key, alert_id, doc_id)
        return {"svi_alert_id": alert_id, "document_id": doc_id, "deduplicated": False}

    # --- Live: OAuth/broker → (opz. entità nel Data Hub) → Alert (triage) ---
    async with httpx.AsyncClient(timeout=settings.svi_request_timeout,
                                 verify=settings.verify_opt()) as client:
        token = await auth.bearer(client)
        auth_h = {"Authorization": f"Bearer {token}"}
        document_id = None
        if settings.svi_load_entity:
            document = mapping.build_document(alert, settings)
            doc_resp = await _retry(
                "datahub/documents",
                lambda: client.post(f"{settings.datahub_base()}/documents", json=document,
                                    headers={**auth_h, "Content-Type": "application/json",
                                             "Accept": "application/json"}),
            )
            document_id = (doc_resp.json() or {}).get("id")

        payload = mapping.build_alerting_payload(alert, settings)
        mt = settings.svi_alertingevent_media_type
        ev_resp = await _retry(
            "alert/alertingEvents",
            lambda: client.post(f"{settings.alerts_base()}/alertingEvents", json=payload,
                                headers={**auth_h, "Content-Type": mt, "Accept": "application/json"}),
        )
        rj = ev_resp.json() if ev_resp.content else {}
        items = rj.get("items") if isinstance(rj, dict) else None
        first = (items[0] if items else rj) or {}
        alert_id = first.get("alertId") or first.get("alertingEventId") or ""
        entity_id = payload["alertingEvents"][0].get("actionableEntityId")

    logger.info("Alerting event SVI creato: alert=%s entity=%s", alert_id, entity_id)
    _idem_put(key, alert_id, document_id)
    return {"svi_alert_id": alert_id, "document_id": document_id, "deduplicated": False}


async def publish_entities(entities: list[dict], relationships: list[dict]) -> None:
    """Carica entità/relazioni nel modello dati SVI (Data Hub API). Placeholder:
    la grafica entità/relazioni è una capability successiva (non parte di B2)."""
    if _is_mock():
        logger.info("[MOCK] Data Hub: %d entità, %d relazioni", len(entities), len(relationships))
        return
    async with httpx.AsyncClient(timeout=settings.svi_request_timeout,
                                 verify=settings.verify_opt()) as client:
        token = await auth.bearer(client)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        await _retry("datahub/links", lambda: client.post(
            f"{settings.datahub_base()}/links",
            json={"entities": entities, "relationships": relationships}, headers=headers))


def reset_idempotency() -> None:
    """Svuota la cache di idempotenza (uso nei test)."""
    _published.clear()
