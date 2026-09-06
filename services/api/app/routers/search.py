"""Anteprima di ricerca articoli (web search) per la console.

`POST /api/search/preview` inoltra al `search-gateway` e restituisce i candidati
(URL, titolo, testata, data, snippet). L'operatore può poi avviare lo screening
sugli articoli scelti (modalità manuale) o affidarsi alla ricerca automatica del
workflow. L'API resta l'unico confine di fiducia: la SPA non chiama il gateway.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/api/search", tags=["search"])


class PreviewRequest(BaseModel):
    tipo_soggetto: str = "persona_giuridica"
    denominazione: str | None = None
    nome: str | None = None
    cognome: str | None = None
    cf_piva: str | None = None
    mode: str = "targeted"              # broad | targeted
    max_results: int | None = None
    min_credibility: str | None = None  # none | bassa | media | alta


@router.post("/preview")
async def preview(req: PreviewRequest) -> dict:
    payload = {
        "subject": {
            "tipo_soggetto": req.tipo_soggetto,
            "denominazione": req.denominazione,
            "nome": req.nome,
            "cognome": req.cognome,
            "cf_piva": req.cf_piva,
        },
        "mode": req.mode,
        "max_results": req.max_results,
        "min_credibility": req.min_credibility,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{settings.search_gateway_url}/v1/search", json=payload)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 — gateway non disponibile
        raise HTTPException(status_code=502, detail=f"ricerca non disponibile: {exc}") from exc
