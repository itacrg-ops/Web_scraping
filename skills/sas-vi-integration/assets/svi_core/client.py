"""Pubblicazione in SAS Visual Investigator — generica, con retry e idempotenza.

Modalità:
  - mock : logga e restituisce id deterministici (sviluppo locale senza Viya);
  - live : OAuth/broker → POST dell'envelope "alerting event".

Robustezza: **retry con backoff** sugli errori transitori; **idempotenza** via business
key. SVI rifiuta un `alertingEventId` già esistente con `errorCode 1008`: essendo l'id
deterministico, è un DUPLICATO dello stesso caso → trattato come successo idempotente,
mai come errore, e non ritentato (il 1008 non è transitorio).
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
    _published.clear()


async def _retry(desc: str, cfg, call: Callable[[], Any]) -> httpx.Response:
    """Esegue `call()` con retry+backoff sugli errori transitori. NON ritenta il data
    error 1008 né i 4xx (terminali): li propaga subito via raise_for_status."""
    last: Exception | None = None
    for attempt in range(cfg.svi_max_retries + 1):
        try:
            resp = await call()
        except httpx.TransportError as exc:
            last = exc
        else:
            if resp.status_code in _RETRYABLE_STATUS and _errcode(resp) != "1008":
                last = httpx.HTTPStatusError(f"{resp.status_code}", request=resp.request, response=resp)
            else:
                resp.raise_for_status()
                return resp
        if attempt >= cfg.svi_max_retries:
            break
        wait = cfg.svi_retry_backoff * (2 ** attempt)
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
    async with httpx.AsyncClient(timeout=cfg.svi_request_timeout, verify=cfg.verify_opt()) as client:
        token = await auth.bearer(client, cfg)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": mt, "Accept": "application/json"}
        logger.info("SVI publish live: key=%s eventId=%s entity=%s score=%s type=%s queue=%s sezioni=%s",
                    key, payload["alertingEvents"][0]["alertingEventId"], alert.entity_id, alert.score,
                    cfg.svi_alert_type_code, cfg.svi_queue, [k for k in payload if k != "jsonLayout"])
        try:
            resp = await _retry("alertingEvents", cfg,
                                lambda: client.post(f"{cfg.alerts_base()}/alertingEvents", json=payload, headers=headers))
            duplicate = False
        except httpx.HTTPStatusError as exc:
            r = exc.response
            if r is not None and r.status_code == 500 and _errcode(r) == "1008":
                logger.info("SVI alertingEvent già presente (1008 duplicato) key=%s → idempotente", key)
                resp, duplicate = r, True
            else:
                raise
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
    return {"svi_alert_id": alert_id, "deduplicated": duplicate}
