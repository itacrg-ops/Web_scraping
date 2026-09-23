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

# Esiti AMBIGUI: la richiesta può essere arrivata a SVI ed essere stata elaborata
# anche se noi non abbiamo visto la risposta (timeout in lettura, connessione caduta,
# 5xx di gateway). Un 1008 successivo per la STESSA chiave è quindi il nostro alert
# già creato, non un errore di configurazione. business_key -> ts del tentativo.
_AMBIGUOUS_STATUS = {500, 502, 504}
_ambiguous: dict[str, float] = {}


class SviRejected(Exception):
    """Rifiuto TERMINALE di SVI (dato/configurazione): ritentare non serve."""


def _ambiguous_transport(exc: httpx.TransportError) -> bool:
    """Connessione mai stabilita → la richiesta non è partita: esito NON ambiguo."""
    return not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))


def _mark_ambiguous(key: str) -> None:
    if len(_ambiguous) > 5000:
        _ambiguous.clear()
    _ambiguous[key] = time.time()


def _was_ambiguous(key: str) -> bool:
    ts = _ambiguous.get(key)
    return ts is not None and (time.time() - ts) < settings.svi_idempotency_ttl


def _errcode(resp: httpx.Response) -> str:
    """errorCode SAS dal corpo (stringa), se presente. Serve a distinguere un 500
    transitorio da un errore di DATO (1008), che non va mai ritentato."""
    try:
        return str((resp.json() or {}).get("errorCode") or "")
    except Exception:  # noqa: BLE001
        return ""


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


async def _retry(desc: str, call: Callable[[], Any], deadline: float | None = None,
                 on_ambiguous: Callable[[], None] | None = None) -> httpx.Response:
    """Esegue `call()` (coroutine factory) con retry+backoff su errori transitori
    (timeout/connessione/5xx/429). Rilancia l'ultimo errore se esauriti i tentativi.

    `deadline` (time.monotonic): non avvia un tentativo che potrebbe sforarla — chi
    ci chiama ha un suo timeout e deve ricevere la risposta prima. `on_ambiguous`:
    invocata quando un tentativo finisce con esito ambiguo (SVI può averlo elaborato)."""
    last: Exception | None = None
    for attempt in range(settings.svi_max_retries + 1):
        try:
            resp = await call()
        except httpx.TransportError as exc:            # timeout/connessione → transitorio
            last = exc
            if on_ambiguous and _ambiguous_transport(exc):
                on_ambiguous()
        else:
            # 5xx/429 transitori → retry, TRANNE il data error 1008 (mai transitorio).
            # Ogni altro esito (2xx, oppure 4xx e 5xx non-retryable incl. 1008) è
            # TERMINALE: raise_for_status lo solleva subito e lo propaga al chiamante.
            if resp.status_code in _RETRYABLE_STATUS and _errcode(resp) != "1008":
                last = httpx.HTTPStatusError(f"{resp.status_code}", request=resp.request, response=resp)
                if on_ambiguous and resp.status_code in _AMBIGUOUS_STATUS:
                    on_ambiguous()
            else:
                resp.raise_for_status()
                return resp
        if attempt >= settings.svi_max_retries:
            break
        wait = settings.svi_retry_backoff * (2 ** attempt)
        if deadline is not None and time.monotonic() + wait + settings.svi_request_timeout > deadline:
            logger.warning("SVI %s: tentativo %d fallito (%s); nessun altro tentativo entro la "
                           "deadline di pubblicazione (SVI_PUBLISH_DEADLINE)", desc, attempt + 1, last)
            break
        logger.warning("SVI %s: tentativo %d fallito (%s), retry tra %.1fs",
                       desc, attempt + 1, last, wait)
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
    deadline = time.monotonic() + settings.svi_publish_deadline
    async with httpx.AsyncClient(timeout=settings.svi_request_timeout,
                                 verify=settings.verify_opt()) as client:
        token = await auth.bearer(client)
        auth_h = {"Authorization": f"Bearer {token}"}
        document_id = None
        if settings.svi_load_entity:
            # Il record entità nel Data Hub è OPZIONALE: l'alerting event crea l'alert
            # anche senza (verificato). Se il caricamento fallisce (es. schema documento
            # non ancora allineato → 400/DH5104) NON deve bloccare l'alert: logga e prosegue.
            document = mapping.build_document(alert, settings)
            try:
                doc_resp = await _retry(
                    "datahub/documents",
                    lambda: client.post(f"{settings.datahub_base()}/documents", json=document,
                                        headers={**auth_h, "Content-Type": "application/json",
                                                 "Accept": "application/json"}),
                    deadline=deadline,
                )
                document_id = (doc_resp.json() or {}).get("id")
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", "—")
                logger.warning("SVI Data Hub: caricamento entità fallito (HTTP %s) key=%s → "
                               "proseguo con l'alert senza record entità: %s", status, key, exc)

        payload = mapping.build_alerting_payload(alert, settings)
        mt = settings.svi_alertingevent_media_type
        ev = payload["alertingEvents"][0]
        entity_id = ev.get("actionableEntityId")
        logger.info("SVI publish live: key=%s eventId=%s entity=%s score=%s type=%s queue=%s sezioni=%s",
                    key, ev.get("alertingEventId"), entity_id, ev.get("score"),
                    ev.get("alertTypeCode"), ev.get("recommendedQueueId"),
                    [k for k in payload if k != "jsonLayout"])
        try:
            ev_resp = await _retry(
                "alert/alertingEvents",
                lambda: client.post(f"{settings.alerts_base()}/alertingEvents", json=payload,
                                    headers={**auth_h, "Content-Type": mt, "Accept": "application/json"}),
                deadline=deadline,
                on_ambiguous=lambda: _mark_ambiguous(key),
            )
            duplicate = False
        except httpx.HTTPStatusError as exc:
            resp = exc.response
            if resp is None or resp.status_code != 500 or _errcode(resp) != "1008":
                raise
            # `errorCode 1008` ("data error") è AMBIGUO: alertingEventId duplicato OPPURE
            # riferimento non risolvibile (dominio/coda/entityType/alertTypeCode
            # inesistenti per l'ambiente). È un duplicato NOSTRO se un tentativo
            # precedente per la stessa chiave ha avuto esito ambiguo (SVI può aver
            # creato l'alert senza che vedessimo la risposta) o con SVI_DEDUP_ON_1008.
            # Altrimenti NON va mascherato da successo: è un rifiuto terminale.
            if _was_ambiguous(key) or settings.svi_dedup_on_1008:
                why = ("dopo un tentativo con esito ambiguo" if _was_ambiguous(key)
                       else "SVI_DEDUP_ON_1008=true")
                logger.info("SVI 1008 key=%s → alert già creato, trattato come duplicato (%s)", key, why)
                ev_resp, duplicate = resp, True
            else:
                logger.error(
                    "SVI 1008 'data error' su alertingEvents key=%s: alert NON creato da questa "
                    "richiesta. Senza tentativi precedenti ambigui la causa tipica è un riferimento "
                    "non valido per QUESTO ambiente (dominio/coda/entityType/alertTypeCode): verifica "
                    "il .env con svi_smoketest.py --diagnose. (Oppure alert già pubblicato prima di un "
                    "riavvio del publisher.) Body: %s", key, (resp.text or "")[:400])
                raise SviRejected(
                    f"SVI errorCode 1008 (data error) per key={key}: riferimento non valido per "
                    f"questo ambiente oppure alert già esistente") from exc
        if duplicate:
            alert_id = mapping.event_id(alert)
        else:
            rj = ev_resp.json() if ev_resp.content else {}
            items = rj.get("items") if isinstance(rj, dict) else None
            first = (items[0] if items else rj) or {}
            alert_id = first.get("alertId") or first.get("alertingEventId") or mapping.event_id(alert)

    esito = "DUPLICATO (già presente, niente di nuovo in coda)" if duplicate else "CREATO"
    logger.info("Alerting event SVI %s: alert=%s entity=%s http=%s dedup=%s",
                esito, alert_id, entity_id, ev_resp.status_code, duplicate)
    _idem_put(key, alert_id, document_id)
    _ambiguous.pop(key, None)
    return {"svi_alert_id": alert_id, "document_id": document_id, "deduplicated": duplicate}


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
    """Svuota la cache di idempotenza e i marcatori di esito ambiguo (uso nei test)."""
    _published.clear()
    _ambiguous.clear()
