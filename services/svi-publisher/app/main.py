"""svi-publisher: microservizio di integrazione verso SAS Visual Investigator.

Espone un'API interna chiamata dal worker per pubblicare alert (ed entità) in
SVI. In produzione il consumo è guidato da coda con pattern *outbox*
(idempotente); qui lo scaffold espone gli endpoint sincroni equivalenti, con
idempotenza in-process e retry verso l'ambiente Viya/SVI.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import svi_client
from app.config import settings

# I log applicativi ("svi_publisher") devono essere visibili anche sotto uvicorn
# (che di default lascia il root a WARNING): diamo al logger un handler proprio a INFO.
_applog = logging.getLogger("svi_publisher")
if not _applog.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    _applog.addHandler(_h)
    _applog.setLevel(logging.INFO)
    _applog.propagate = False

app = FastAPI(title="SVI Publisher", version="0.2.0")


class EvidenceIn(BaseModel):
    url: str | None = None
    testata: str | None = None
    title: str | None = None
    data: str | None = None
    snippet: str | None = None
    content_hash: str | None = None
    fetch_ts: str | None = None
    warc_key: str | None = None
    fonte_credibilita: str | None = None


class AlertIn(BaseModel):
    subject: str
    tipo_soggetto: str | None = None
    cf_piva: str | None = None
    cup: list[str] = []
    ami_score: int
    risk_level: str
    fatf_categories: list[str] = []
    drivers: list[str] = []              # motivazione (esplicabilità)
    disposition: str = "ESCALATION_I_LIVELLO"
    screening_id: str | None = None      # business key per l'idempotenza
    evidence: list[EvidenceIn] = []


class PublishOut(BaseModel):
    svi_alert_id: str
    mode: str
    deduplicated: bool = False
    document_id: str | None = None


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "mode": settings.svi_mode, "auth": settings.svi_auth_mode}


@app.post("/publish/alert", response_model=PublishOut)
async def publish_alert(alert: AlertIn) -> PublishOut:
    """Pubblica l'alert. Errori con semantica per il chiamante (worker):
    **422** = rifiuto terminale (dato/configurazione SVI: ritentare non serve);
    **502** = SVI non disponibile/transitorio (il chiamante può ritentare)."""
    try:
        res = await svi_client.publish_alert(alert.model_dump())
    except svi_client.SviRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        body = (exc.response.text or "")[:300]
        if 400 <= code < 500 and code not in (408, 429):
            raise HTTPException(status_code=422, detail=f"SVI ha rifiutato la richiesta (HTTP {code}): {body}") from exc
        raise HTTPException(status_code=502, detail=f"SVI non disponibile (HTTP {code}): {body}") from exc
    except httpx.TransportError as exc:
        raise HTTPException(status_code=502, detail=f"SVI non raggiungibile: {exc!r}") from exc
    return PublishOut(svi_alert_id=res["svi_alert_id"], mode=settings.svi_mode,
                      deduplicated=res["deduplicated"], document_id=res.get("document_id"))
