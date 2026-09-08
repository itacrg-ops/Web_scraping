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
    azienda: str | None = None          # persona fisica: qualificatore (query AND)
    localita: str | None = None         # persona fisica: qualificatore (query AND)
    ruolo: str | None = None            # persona fisica: soft (non in query)
    mode: str = "targeted"              # broad | targeted
    max_results: int | None = None
    min_credibility: str | None = None  # none | bassa | media | alta


@router.get("/providers")
async def providers() -> dict:
    """Stato dei motori di ricerca web (proxy verso il search-gateway) per la
    pagina Fonti: quali sono attivi e il catalogo disponibile."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{settings.search_gateway_url}/v1/providers")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 — gateway non disponibile
        raise HTTPException(status_code=502, detail=f"stato provider non disponibile: {exc}") from exc


@router.post("/preview")
async def preview(req: PreviewRequest) -> dict:
    payload = {
        "subject": {
            "tipo_soggetto": req.tipo_soggetto,
            "denominazione": req.denominazione,
            "nome": req.nome,
            "cognome": req.cognome,
            "cf_piva": req.cf_piva,
            "azienda": req.azienda,
            "localita": req.localita,
            "ruolo": req.ruolo,
        },
        "mode": req.mode,
        "max_results": req.max_results,
        "min_credibility": req.min_credibility,
    }
    try:
        # timeout ampio: il gateway può attendere per il throttle/retry di GDELT.
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(f"{settings.search_gateway_url}/v1/search", json=payload)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 — gateway non disponibile
        raise HTTPException(status_code=502, detail=f"ricerca non disponibile: {exc}") from exc
