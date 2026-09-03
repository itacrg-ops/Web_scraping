"""Gateway LLM: punto unico di governo verso Azure AI Foundry (§10)."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app import foundry

app = FastAPI(title="LLM Gateway — Azure AI Foundry", version="0.1.0")


class ClassifyRequest(BaseModel):
    text: str
    dual: bool = True  # se True, esegue anche la validazione col modello secondario


class ClassifyResponse(BaseModel):
    primary: str
    secondary: str | None = None


@app.get("/healthz")
def healthz() -> dict[str, str]:
    # Health non dipende dalla credenziale: il servizio parte comunque.
    return {"status": "ok", "endpoint_configured": bool(settings.azure_foundry_endpoint)}


@app.post("/v1/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest) -> ClassifyResponse:
    try:
        primary = foundry.classify(req.text, secondary=False)
        secondary = foundry.classify(req.text, secondary=True) if req.dual else None
    except RuntimeError as exc:  # configurazione mancante / credenziale assente
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ClassifyResponse(primary=primary, secondary=secondary)
