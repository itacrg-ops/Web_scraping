"""Activity dello scraping (scaffold).

Ogni activity è **idempotente** (chiave = hash contenuto + versione): retry
di Temporal e repliche concorrenti non duplicano evidenze (§4.4 / §6.4).
Qui sono placeholder: la logica reale (fetch conforme robots/ToS/opt-out TDM,
estrazione, deduplica, provenance + marca temporale eIDAS) va implementata.
"""
from __future__ import annotations

from temporalio import activity


@activity.defn
async def fetch_source(url: str) -> dict:
    """Placeholder: recupero conforme di una pagina/fonte."""
    activity.logger.info("fetch_source (stub): %s", url)
    # TODO: HTTP client + headless browser, robots.txt, rate limiting, provenance.
    return {"url": url, "status": "stub", "content_hash": "sha256:TODO"}


@activity.defn
async def extract_content(raw: dict) -> dict:
    """Placeholder: boilerplate removal + estrazione testo/metadati."""
    activity.logger.info("extract_content (stub)")
    # TODO: trafilatura/readability, dedup, filtro lingua/pertinenza.
    return {"text": "", "meta": {}, "source": raw.get("url")}
