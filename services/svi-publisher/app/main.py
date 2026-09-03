"""svi-publisher: microservizio di integrazione verso SAS Visual Investigator.

Espone un'API interna chiamata dal `worker-conflict-resolution` per pubblicare
alert ed entità in SVI. In produzione il consumo è guidato da coda con pattern
*outbox* (idempotente); qui lo scaffold espone gli endpoint sincroni equivalenti.
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import settings
from app import svi_client

app = FastAPI(title="SVI Publisher", version="0.1.0")


class AlertIn(BaseModel):
    subject: str
    cf_piva: str | None = None
    cup: list[str] = []
    ami_score: int
    risk_level: str
    fatf_categories: list[str] = []
    drivers: list[str] = []
    disposition: str = "ESCALATION_I_LIVELLO"


class PublishOut(BaseModel):
    svi_alert_id: str
    mode: str


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "mode": settings.svi_mode}


@app.post("/publish/alert", response_model=PublishOut)
async def publish_alert(alert: AlertIn) -> PublishOut:
    svi_alert_id = await svi_client.publish_alert(alert.model_dump())
    return PublishOut(svi_alert_id=svi_alert_id, mode=settings.svi_mode)
