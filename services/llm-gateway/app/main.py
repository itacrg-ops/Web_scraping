"""Gateway LLM: punto unico di governo verso Azure AI Foundry (§10).

Espone la classificazione FATF strutturata (dual-LLM) come JSON tipizzato.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import foundry
from app.config import settings

logger = logging.getLogger("llm-gateway")

app = FastAPI(title="LLM Gateway — Azure AI Foundry", version="0.2.0")


class ClassifyRequest(BaseModel):
    text: str
    dual: bool = True  # se True, esegue anche la validazione col modello secondario


class ClassifyResponse(BaseModel):
    fatf_categories: list[str] = []
    ruolo_processuale: str | None = None
    role_analysis: str | None = None
    severity: str | None = None
    confidence: float = 0.0
    rationale: str | None = None
    secondary_agreement: bool | None = None
    method: str
    models: dict
    # Audit redazione PII: {"total": n, "by_category": {...}} (solo conteggi).
    pii_redaction: dict | None = None


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedResponse(BaseModel):
    model: str
    dims: int
    embeddings: list[list[float]] = []


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "endpoint_configured": bool(settings.azure_foundry_endpoint),
        "embedding_configured": bool(settings.embedding_model),
        "auth_mode": "api_key" if settings.azure_api_key else "entra",
    }


@app.post("/v1/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest) -> dict:
    try:
        return foundry.classify(req.text, dual=req.dual)
    except RuntimeError as exc:  # configurazione/credenziale mancante
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — errore modello/parsing JSON
        logger.warning("Classificazione fallita: %s", exc)
        raise HTTPException(status_code=502, detail=f"classificazione non riuscita: {exc}") from exc


@app.post("/v1/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> dict:
    """Embedding dei testi (Azure AI Foundry) per la similarità semantica dei
    nomi nell'Entity Resolution (B7)."""
    try:
        return foundry.embed(req.texts)
    except RuntimeError as exc:  # embedding non configurato
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding fallito: %s", exc)
        raise HTTPException(status_code=502, detail=f"embedding non riuscito: {exc}") from exc
