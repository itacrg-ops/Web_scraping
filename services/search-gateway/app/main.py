"""search-gateway: ricerca di articoli adverse-media per un soggetto.

Espone `/v1/search`: dato un soggetto (persona fisica o giuridica) costruisce la
query (nome + termini avversi FATF) e interroga il provider configurato
(`mock` di default, `gdelt` keyless). Ritorna i candidati (URL, titolo, testata,
data, snippet) che poi vengono verificati e passati alla pipeline di screening.
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app import providers
from app import query as qb
from app.config import settings

app = FastAPI(title="Search Gateway — Adverse Media", version="0.1.0")


class SubjectIn(BaseModel):
    tipo_soggetto: str = "persona_giuridica"
    denominazione: str | None = None
    nome: str | None = None
    cognome: str | None = None
    cf_piva: str | None = None


class SearchRequest(BaseModel):
    subject: SubjectIn
    mode: str = "targeted"          # broad | targeted
    max_results: int | None = None
    lang: str | None = None         # override del filtro lingua (None = default)
    timespan: str | None = None


class SearchResultOut(BaseModel):
    url: str
    title: str | None = None
    snippet: str | None = None
    testata: str | None = None
    data: str | None = None
    language: str | None = None
    provider: str
    score: float | None = None


class SearchResponse(BaseModel):
    provider: str
    query: str
    mode: str
    count: int
    results: list[SearchResultOut] = []


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "provider": settings.search_provider}


@app.post("/v1/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> dict:
    subject = req.subject.model_dump()
    mode = req.mode if req.mode in ("broad", "targeted") else "targeted"
    query_str = qb.build_query(subject, mode)
    max_results = req.max_results or settings.search_max_results
    lang = settings.search_default_lang if req.lang is None else req.lang
    timespan = req.timespan or settings.search_timespan

    results = await providers.search(query_str, subject, mode, max_results, lang, timespan)
    return {
        "provider": settings.search_provider,
        "query": query_str,
        "mode": mode,
        "count": len(results),
        "results": results,
    }
