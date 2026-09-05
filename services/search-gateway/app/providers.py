"""Provider di ricerca (astrazione con più backend).

- `mock` (default): risultati deterministici, nessuna rete. Serve allo sviluppo
  locale e all'anteprima in console senza dipendenze esterne.
- `gdelt`: GDELT DOC 2.0 API (news globale, **keyless**). Adatto a locale/pilota.

Altri provider (Bing/Brave/SerpAPI/Google CSE via API key, o feed licenziati tipo
Dow Jones/Factiva) si aggiungono qui implementando la stessa firma e restituendo
la stessa forma di risultato.
"""
from __future__ import annotations

import logging

import httpx

from app import query as qb
from app.config import settings

logger = logging.getLogger("search-gateway.providers")


def _result(url, title=None, snippet=None, testata=None, data=None,
            language=None, provider="mock", score=None) -> dict:
    return {
        "url": url, "title": title, "snippet": snippet, "testata": testata,
        "data": data, "language": language, "provider": provider, "score": score,
    }


# --- Provider mock: fixtures deterministiche -------------------------------
_MOCK_TESTATE = [
    ("ilmessaggero-esempio.example.com", "Il Messaggero (esempio)"),
    ("repubblica-esempio.example.com", "la Repubblica (esempio)"),
    ("ansa-esempio.example.org", "ANSA (esempio)"),
]
_MOCK_TITLES = [
    "Inchiesta appalti: perquisizioni e indagati, coinvolto {name}",
    "Corruzione e turbativa d'asta: {name} tra i nomi nel fascicolo",
    "Sequestro e accuse di frode: verifiche in corso su {name}",
]
_MOCK_DATES = ["2026-03-26", "2026-02-14", "2025-12-03"]


def _mock(subject: dict, mode: str, max_results: int) -> list[dict]:
    names = qb.name_variants(subject)
    if not names:
        return []
    display = names[0]
    slug = display.lower().replace(" ", "-").replace("'", "")
    out: list[dict] = []
    for i, (domain, testata) in enumerate(_MOCK_TESTATE):
        out.append(_result(
            url=f"https://{domain}/adverse-media/{slug}-{i + 1}",
            title=_MOCK_TITLES[i % len(_MOCK_TITLES)].format(name=display),
            snippet=(f"Secondo fonti giudiziarie, {display} risulterebbe coinvolto in "
                     f"un'inchiesta su appalti pubblici (contenuto di esempio, provider mock)."),
            testata=testata, data=_MOCK_DATES[i % len(_MOCK_DATES)],
            language="Italian", provider="mock", score=round(1.0 - i * 0.1, 2),
        ))
    return out[:max_results]


# --- Provider GDELT DOC 2.0 (keyless) --------------------------------------
def _fmt_gdelt_date(seendate: str | None) -> str | None:
    # GDELT seendate: "YYYYMMDDTHHMMSSZ" -> "YYYY-MM-DD"
    if not seendate or len(seendate) < 8:
        return None
    return f"{seendate[0:4]}-{seendate[4:6]}-{seendate[6:8]}"


async def _gdelt(query_str: str, max_results: int, lang: str, timespan: str) -> list[dict]:
    if not query_str:
        return []
    q = f"{query_str} sourcelang:{lang}" if lang else query_str
    params = {
        "query": q, "mode": "ArtList", "format": "json",
        "maxrecords": str(max(1, min(max_results, 250))),
        "sort": "DateDesc", "timespan": timespan,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout,
                                     headers={"User-Agent": settings.user_agent}) as c:
            r = await c.get(settings.gdelt_endpoint, params=params)
        if r.status_code != 200:
            logger.warning("GDELT status %s", r.status_code)
            return []
        try:
            data = r.json()
        except Exception:  # noqa: BLE001 — GDELT può rispondere HTML su query invalide
            logger.warning("GDELT: risposta non-JSON (query rifiutata?)")
            return []
    except Exception as exc:  # noqa: BLE001 — rete non fatale
        logger.warning("GDELT non raggiungibile: %s", exc)
        return []

    out: list[dict] = []
    for a in (data.get("articles") or []):
        url = a.get("url") or a.get("url_mobile")
        if not url:
            continue
        out.append(_result(
            url=url, title=a.get("title"), snippet=None,
            testata=a.get("domain"), data=_fmt_gdelt_date(a.get("seendate")),
            language=a.get("language"), provider="gdelt", score=None,
        ))
    return out


async def search(query_str: str, subject: dict, mode: str, max_results: int,
                 lang: str, timespan: str) -> list[dict]:
    if settings.search_provider == "gdelt":
        return await _gdelt(query_str, max_results, lang, timespan)
    return _mock(subject, mode, max_results)
