"""Pubblicazione in SAS Visual Investigator — generica, con retry e idempotenza.

Modalità:
  - mock : logga e restituisce id deterministici (sviluppo locale senza Viya);
  - live : OAuth/broker → POST dell'envelope "alerting event".

Robustezza: **retry con backoff** sugli errori transitori, entro una **deadline**
complessiva (`svi_publish_deadline`); **idempotenza** via business key (alertingEventId
deterministico).

`errorCode 1008` ("data error") è AMBIGUO: alertingEventId già esistente OPPURE
riferimento non valido per l'ambiente (dominio/coda/entityType/alertTypeCode). È
trattato come duplicato SOLO se un tentativo precedente per la stessa chiave ha avuto
esito ambiguo (timeout in lettura / 5xx: SVI può aver creato l'alert senza che
vedessimo la risposta) o con `svi_dedup_on_1008`; altrimenti solleva `SviRejected`
(terminale: non ritentare). Mai ritentato (il 1008 non è transitorio).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

import httpx

from . import auth
from .config import settings as _default_settings
from .envelope import build_alerting_payload
from .models import SviAlert

logger = logging.getLogger("svi_core")

# Cache di idempotenza in-process: business_key -> (ts, alert_id). In prod: outbox/Redis.
_published: dict[str, tuple[float, str]] = {}
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Esiti AMBIGUI (la richiesta può essere stata elaborata): business_key -> ts.
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


def _was_ambiguous(key: str, ttl: int) -> bool:
    ts = _ambiguous.get(key)
    return ts is not None and (time.time() - ts) < ttl


def _errcode(resp: httpx.Response) -> str:
    try:
        return str((resp.json() or {}).get("errorCode") or "")
    except Exception:  # noqa: BLE001
        return ""


def _idem_get(key: str, ttl: int) -> str | None:
    hit = _published.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _idem_put(key: str, alert_id: str) -> None:
    if len(_published) > 5000:
        _published.clear()
    _published[key] = (time.time(), alert_id)


def reset_idempotency() -> None:
    """Svuota cache di idempotenza e marcatori di esito ambiguo (test)."""
    _published.clear()
    _ambiguous.clear()


async def _retry(desc: str, cfg, call: Callable[[], Any], deadline: float | None = None,
                 on_ambiguous: Callable[[], None] | None = None) -> httpx.Response:
    """Esegue `call()` con retry+backoff sugli errori transitori. NON ritenta il data
    error 1008 né i 4xx (terminali): li propaga subito via raise_for_status.
    Non avvia un tentativo che potrebbe sforare `deadline` (time.monotonic);
    `on_ambiguous` segnala i tentativi con esito ambiguo."""
    last: Exception | None = None
    for attempt in range(cfg.svi_max_retries + 1):
        try:
            resp = await call()
        except httpx.TransportError as exc:
            last = exc
            if on_ambiguous and _ambiguous_transport(exc):
                on_ambiguous()
        else:
            if resp.status_code in _RETRYABLE_STATUS and _errcode(resp) != "1008":
                last = httpx.HTTPStatusError(f"{resp.status_code}", request=resp.request, response=resp)
                if on_ambiguous and resp.status_code in _AMBIGUOUS_STATUS:
                    on_ambiguous()
            else:
                resp.raise_for_status()
                return resp
        if attempt >= cfg.svi_max_retries:
            break
        wait = cfg.svi_retry_backoff * (2 ** attempt)
        if deadline is not None and time.monotonic() + wait + cfg.svi_request_timeout > deadline:
            logger.warning("SVI %s: tentativo %d fallito (%s); nessun altro tentativo entro la deadline",
                           desc, attempt + 1, last)
            break
        logger.warning("SVI %s: tentativo %d fallito (%s), retry tra %.1fs", desc, attempt + 1, last, wait)
        await asyncio.sleep(wait)
    raise last if last else RuntimeError(f"SVI {desc}: fallito")


def _is_mock(cfg) -> bool:
    return cfg.svi_mode.lower() != "live"


async def publish(alert: SviAlert, cfg=None) -> dict[str, Any]:
    """Pubblica un `SviAlert` in modo idempotente. Ritorna {svi_alert_id, deduplicated}."""
    cfg = cfg or _default_settings
    key = alert.business_key

    cached = _idem_get(key, cfg.svi_idempotency_ttl)
    if cached is not None:
        logger.info("SVI alert già pubblicato (idempotenza) key=%s id=%s", key, cached)
        return {"svi_alert_id": cached, "deduplicated": True}

    if _is_mock(cfg):
        alert_id = f"svi-mock-{alert.event_id()[:8]}"
        logger.info("[MOCK] Alert SVI: %s (entity=%s, score=%s)", alert_id, alert.entity_id, alert.score)
        _idem_put(key, alert_id)
        return {"svi_alert_id": alert_id, "deduplicated": False}

    payload = build_alerting_payload(alert, cfg)
    mt = cfg.svi_alertingevent_media_type
    deadline = time.monotonic() + cfg.svi_publish_deadline
    async with httpx.AsyncClient(timeout=cfg.svi_request_timeout, verify=cfg.verify_opt()) as client:
        token = await auth.bearer(client, cfg)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": mt, "Accept": "application/json"}
        logger.info("SVI publish live: key=%s eventId=%s entity=%s score=%s type=%s queue=%s sezioni=%s",
                    key, payload["alertingEvents"][0]["alertingEventId"], alert.entity_id, alert.score,
                    cfg.svi_alert_type_code, cfg.svi_queue, [k for k in payload if k != "jsonLayout"])
        try:
            resp = await _retry("alertingEvents", cfg,
                                lambda: client.post(f"{cfg.alerts_base()}/alertingEvents", json=payload, headers=headers),
                                deadline=deadline, on_ambiguous=lambda: _mark_ambiguous(key))
            duplicate = False
        except httpx.HTTPStatusError as exc:
            r = exc.response
            if r is None or r.status_code != 500 or _errcode(r) != "1008":
                raise
            # 1008 AMBIGUO (vedi docstring del modulo): duplicato NOSTRO solo dopo un
            # tentativo ambiguo per la stessa chiave, o con svi_dedup_on_1008.
            ambiguous = _was_ambiguous(key, cfg.svi_idempotency_ttl)
            if ambiguous or getattr(cfg, "svi_dedup_on_1008", False):
                why = "dopo un tentativo con esito ambiguo" if ambiguous else "svi_dedup_on_1008=true"
                logger.info("SVI 1008 key=%s → alert già creato, trattato come duplicato (%s)", key, why)
                resp, duplicate = r, True
            else:
                logger.error("SVI 1008 'data error' key=%s: alert NON creato da questa richiesta. Senza "
                             "tentativi ambigui la causa tipica è un riferimento non valido per QUESTO "
                             "ambiente (dominio/coda/entityType/alertTypeCode: svi_inspect.py) o un alert "
                             "già pubblicato prima di un riavvio. Body: %s", key, (r.text or "")[:400])
                raise SviRejected(f"SVI errorCode 1008 per key={key}: riferimento non valido per "
                                  f"questo ambiente oppure alert già esistente") from exc
        if duplicate:
            alert_id = alert.event_id()
        else:
            rj = resp.json() if resp.content else {}
            items = rj.get("items") if isinstance(rj, dict) else None
            first = (items[0] if items else rj) or {}
            alert_id = first.get("alertId") or first.get("alertingEventId") or alert.event_id()

    esito = "DUPLICATO" if duplicate else "CREATO"
    logger.info("Alerting event SVI %s: alert=%s entity=%s dedup=%s", esito, alert_id, alert.entity_id, duplicate)
    _idem_put(key, alert_id)
    _ambiguous.pop(key, None)
    return {"svi_alert_id": alert_id, "deduplicated": duplicate}
