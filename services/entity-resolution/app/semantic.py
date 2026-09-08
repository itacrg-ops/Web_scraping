"""Similarità semantica via embedding (B7) attraverso il llm-gateway.

Client sincrono (il resolver è sincrono) verso `POST /v1/embed` del llm-gateway,
che espone gli embedding di Azure AI Foundry. Usato per fondere una componente
**semantica** nella similarità del nome (varianti/abbreviazioni che la similarità
di stringa sottostima).

NON fatale per definizione: su assenza di configurazione, timeout o errore
ritorna `None` e il resolver resta sulla sola similarità di stringa.
"""
from __future__ import annotations

import logging
import math

import httpx

from app.config import settings

logger = logging.getLogger("entity-resolution.semantic")


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    # clamp in [0,1]: le similarità coseno negative non ci servono (0 = nessuna).
    return max(0.0, min(1.0, dot / (na * nb)))


def similarities(query: str, candidates: list[str]) -> list[float] | None:
    """Ritorna la similarità coseno [0..1] tra `query` e ciascun `candidates`,
    oppure `None` se gli embedding non sono disponibili (→ fallback a stringa)."""
    if not query or not candidates:
        return None
    texts = [query, *candidates]
    try:
        r = httpx.post(
            f"{settings.llm_gateway_url}/v1/embed",
            json={"texts": texts},
            timeout=settings.embedding_timeout,
        )
        if r.status_code != 200:
            logger.info("embed non disponibile (HTTP %s): fallback a similarità di stringa", r.status_code)
            return None
        vecs = r.json().get("embeddings") or []
    except Exception as exc:  # noqa: BLE001 — non fatale
        logger.info("embed non raggiungibile (%s): fallback a similarità di stringa", exc)
        return None

    if len(vecs) != len(texts):
        logger.info("embed: numero di vettori inatteso (%d/%d): fallback", len(vecs), len(texts))
        return None
    q, cand_vecs = vecs[0], vecs[1:]
    return [_cosine(q, cv) for cv in cand_vecs]
