"""search-gateway: ricerca di articoli adverse-media per un soggetto.

Espone `/v1/search`: dato un soggetto (persona fisica o giuridica) costruisce la
query (nome + termini avversi FATF) e interroga il provider configurato
(`mock` di default, `gdelt` keyless). Ritorna i candidati (URL, titolo, testata,
data, snippet) che poi vengono verificati e passati alla pipeline di screening.
"""
from __future__ import annotations

import time

from fastapi import FastAPI
from pydantic import BaseModel

from app import providers
from app import testate
from app.config import settings

app = FastAPI(title="Search Gateway — Adverse Media", version="0.1.0")

# Cache in-memory dei risultati GREZZI del provider (pre-dedup/filtro), così
# ricerche ripetute nel loop di test non ribattono su GDELT (rate-limited).
# Chiave: parametri che determinano la risposta del provider. TTL da config.
_cache: dict[tuple, tuple[float, list, str]] = {}


def _cache_get(key: tuple):
    hit = _cache.get(key)
    if hit and (time.monotonic() - hit[0]) < settings.search_cache_ttl:
        return hit[1], hit[2]
    return None


def _cache_put(key: tuple, raw: list, query_used: str) -> None:
    if settings.search_cache_ttl <= 0:
        return
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = (time.monotonic(), raw, query_used)


class SubjectIn(BaseModel):
    tipo_soggetto: str = "persona_giuridica"
    denominazione: str | None = None
    nome: str | None = None
    cognome: str | None = None
    cf_piva: str | None = None
    # Qualificatori (persona fisica): azienda e località entrano nella query in
    # AND forte; il ruolo è soft (non nella query).
    azienda: str | None = None
    localita: str | None = None
    ruolo: str | None = None


class SearchRequest(BaseModel):
    subject: SubjectIn
    mode: str = "targeted"          # broad | targeted
    max_results: int | None = None
    lang: str | None = None         # override del filtro lingua (None = default)
    timespan: str | None = None
    min_credibility: str | None = None  # override soglia credibilità (none|bassa|media|alta)


class SearchResultOut(BaseModel):
    url: str
    title: str | None = None
    snippet: str | None = None
    testata: str | None = None
    domain: str | None = None
    testata_credibilita: str | None = None
    data: str | None = None
    language: str | None = None
    provider: str
    score: float | None = None


class SearchResponse(BaseModel):
    provider: str
    query: str
    mode: str
    count: int
    raw_count: int          # risultati grezzi prima di dedup/filtro
    removed: int            # rimossi da filtro credibilità + dedup per dominio
    min_credibility: str
    note: str | None = None  # avviso (es. GDELT rate-limited / non raggiungibile)
    results: list[SearchResultOut] = []


class CredibilityRequest(BaseModel):
    urls: list[str] = []


class CredibilityItem(BaseModel):
    url: str
    domain: str | None = None
    testata_credibilita: str


class CredibilityResponse(BaseModel):
    items: list[CredibilityItem] = []


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "provider": settings.search_provider}


@app.post("/v1/credibility", response_model=CredibilityResponse)
def credibility(req: CredibilityRequest) -> dict:
    """Annota una lista di URL con dominio registrabile e credibilità della
    testata (registro unico `testate.py`). Usato dal worker per pesare l'AMI
    su tutti i percorsi (ricerca automatica, articoli scelti, URL singolo)."""
    items = []
    for u in req.urls:
        d = testate.domain_of(u)
        items.append({
            "url": u,
            "domain": d or None,
            "testata_credibilita": testate.credibility_of(d) if d else "sconosciuta",
        })
    return {"items": items}


@app.post("/v1/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> dict:
    subject = req.subject.model_dump()
    mode = req.mode if req.mode in ("broad", "targeted") else "targeted"
    max_results = req.max_results or settings.search_max_results
    lang = settings.search_default_lang if req.lang is None else req.lang
    timespan = req.timespan or settings.search_timespan
    min_cred = req.min_credibility if req.min_credibility is not None else settings.min_credibility

    # Over-fetch dal provider, così dopo la dedup restano abbastanza domini distinti.
    fetch_n = min(max_results * settings.dedup_overfetch, 250) if settings.dedup_by_domain else max_results

    # Cache sui risultati grezzi (indipendente dal filtro credibilità, applicato dopo).
    cache_key = (
        settings.search_provider, mode, fetch_n, lang, timespan,
        subject.get("tipo_soggetto"), subject.get("denominazione"),
        subject.get("nome"), subject.get("cognome"),
        # azienda/località entrano nella query → devono invalidare la cache.
        subject.get("azienda"), subject.get("localita"),
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        raw, query_used, note = cached[0], cached[1], None
    else:
        raw, query_used, note = await providers.search(subject, mode, fetch_n, lang, timespan)
        if note is None:  # cache solo risposte pulite (non 429/errori)
            _cache_put(cache_key, raw, query_used)

    results, removed = testate.postprocess(
        raw,
        dedup_by_domain=settings.dedup_by_domain,
        max_per_domain=settings.max_per_domain,
        min_credibility=min_cred,
        max_results=max_results,
    )
    return {
        "provider": settings.search_provider,
        "query": query_used,
        "mode": mode,
        "count": len(results),
        "raw_count": len(raw),
        "removed": removed,
        "min_credibility": min_cred,
        "note": note,
        "results": results,
    }
