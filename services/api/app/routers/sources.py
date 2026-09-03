"""Registro fonti (§5.1). Scaffold: store in memoria — sostituire con Postgres."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import Source

router = APIRouter(prefix="/api/sources", tags=["sources"])

# Store temporaneo in memoria (placeholder). TODO: repository su PostgreSQL.
_SEED: dict[str, Source] = {
    "dowjones": Source(
        id="dowjones", nome="Dow Jones Risk & Compliance", tipo="feed",
        credibilita="alta", rischio_legale="basso", attiva=True,
    ),
    "anac-bdncp": Source(
        id="anac-bdncp", nome="BDNCP — ANAC (via PDND)", tipo="api",
        credibilita="alta", rischio_legale="basso", attiva=True,
    ),
    "albo-pretorio": Source(
        id="albo-pretorio", nome="Albo pretorio (comune X)", tipo="scraping",
        credibilita="alta", rischio_legale="basso", crawl_delay_s=3.0, attiva=True,
    ),
}


@router.get("")
def list_sources() -> list[Source]:
    return list(_SEED.values())


@router.get("/{source_id}")
def get_source(source_id: str) -> Source:
    if source_id not in _SEED:
        raise HTTPException(status_code=404, detail="fonte non trovata")
    return _SEED[source_id]


@router.put("/{source_id}")
def upsert_source(source_id: str, source: Source) -> Source:
    _SEED[source_id] = source
    return source
