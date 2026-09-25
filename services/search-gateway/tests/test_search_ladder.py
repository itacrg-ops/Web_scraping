"""Scala di query cumulativa, ricerca web + news in SearXNG, siti che non sono notizie,
diagnostica per motore. Motori simulati: nessuna rete.

Caso reale: «Only Italia Logistics S.r.l.» — Google trova diversi articoli, la ricerca
ne trovava uno: la query «nome + termini avversi» (per i motori web tutti richiesti)
dava un solo risultato e la scala si fermava lì, senza cercare il solo nome.

    python services/search-gateway/tests/test_search_ladder.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app import main, providers, testate  # noqa: E402
from app import query as qb  # noqa: E402
from app.config import settings  # noqa: E402

ONLY = {"tipo_soggetto": "persona_giuridica", "denominazione": "Only Italia Logistics S.r.l."}


def _res(url: str, title: str = "") -> dict:
    return {"url": url, "title": title or url, "snippet": None, "testata": None, "data": None,
            "language": None, "provider": "searxng", "score": None}


def _run(subject: dict, answers, provider: str = "searxng", **extra) -> tuple[dict, list[str]]:
    """POST /v1/search con SearXNG simulato: `answers(q)` → (status, risultati, motori_giù)."""
    calls: list[str] = []

    async def fake_call(q, max_results, timeout=None):
        calls.append(q)
        return answers(q)

    saved = (settings.search_provider, providers._searxng_call)
    settings.search_provider, providers._searxng_call = provider, fake_call
    main._cache.clear()
    try:
        async def _call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
                return await c.post("/v1/search", json={"subject": subject, "max_results": 10, **extra})
        r = asyncio.run(_call())
        assert r.status_code == 200, r.text
        return r.json(), calls
    finally:
        settings.search_provider, providers._searxng_call = saved


def _only_answers(q: str):
    if qb.has_adverse_terms(q):     # nome + termini avversi: un solo articolo
        return "ok", [_res("https://www.ilgiorno.it/cronaca/only-italia-logistics-sequestro")], []
    return "ok", [_res(f"https://www.testata{i}.it/only-italia-logistics") for i in range(6)] + [
        _res("https://www.ilgiorno.it/cronaca/only-italia-logistics-sequestro"),      # già trovato
        _res("https://www.reportaziende.it/only_italia_logistics_srl"),              # scheda d'impresa
        _res("https://it.linkedin.com/company/only-italia-logistics"),               # social
    ], []


def test_ladder_adds_name_only_results() -> None:
    d, calls = _run(ONLY, _only_answers)
    assert calls == ['"Only Italia Logistics" ' + " ".join(qb.ADVERSE_TERMS), '"Only Italia Logistics"']
    urls = [r["url"] for r in d["results"]]
    assert len(urls) == 7, urls                                   # 1 + 6 testate, senza doppioni
    assert urls[0].startswith("https://www.ilgiorno.it/") and d["results"][0]["adverse_query"] is True
    assert all(r["adverse_query"] is False for r in d["results"][1:])
    assert not any("reportaziende" in u or "linkedin" in u for u in urls)   # non sono notizie
    assert d["removed"] == 2 and d["error"] is None
    eng = d["engines"][0]
    assert eng["provider"] == "searxng" and eng["count"] == 9 and len(eng["queries"]) == 2


def test_ladder_stops_when_enough() -> None:
    many = [_res(f"https://www.t{i}.it/a") for i in range(40)]
    d, calls = _run(ONLY, lambda q: ("ok", many, []))
    assert len(calls) == 1 and d["count"] == 10


def test_person_with_company_keeps_fallback_only() -> None:
    person = {"tipo_soggetto": "persona_fisica", "nome": "Mario", "cognome": "Rossi", "azienda": "Acme"}
    d, calls = _run(person, lambda q: ("ok", [_res("https://www.ansa.it/rossi-acme")], []))
    assert calls == ['"Mario Rossi" "Acme"'] and d["count"] == 1   # nessun allargamento agli omonimi


def test_later_failure_keeps_found_results() -> None:
    def answers(q):
        if qb.has_adverse_terms(q):
            return "ok", [_res("https://www.ansa.it/a"), _res("https://www.corriere.it/b")], []
        return "error", "SearXNG ha risposto 502.", []
    d, _ = _run(ONLY, answers)
    assert d["count"] == 2 and d["error"] is None and "ricerca parziale" in d["note"]


def test_no_results_while_engines_down_is_an_error() -> None:
    d, _ = _run(ONLY, lambda q: ("ok", [], ["google cse: timeout", "duckduckgo: CAPTCHA"]))
    assert d["count"] == 0 and d["error"] and "google cse: timeout" in d["error"]
    assert d["engines"][0]["non_disponibili"] == ["google cse: timeout", "duckduckgo: CAPTCHA"]


def test_engines_down_with_results_is_not_a_warning() -> None:
    # normale: un motore interno blocca o cambia pagina, gli altri rispondono
    d, _ = _run(ONLY, lambda q: ("ok", [_res(f"https://www.t{hash(q) % 97}.it/x")], ["google cse: timeout"]))
    assert d["count"] >= 1 and d["error"] is None and d["note"] is None
    assert d["engines"][0]["non_disponibili"] == ["google cse: timeout"]


def test_engines_down_are_translated_and_not_repeated() -> None:
    # caso reale: ANSA segnalato due volte (errore, poi «Suspended»)
    reported = [["ansa", "HTTP error"], ["bing news", "parsing error"], ["startpage", "CAPTCHA"],
                ["startpage news", "CAPTCHA"], ["ansa", "Suspended: HTTP error"], ["reuters", "Suspended: boh"]]
    assert providers._engines_down(reported) == [
        "ansa: errore HTTP", "bing news: pagina non leggibile", "startpage: CAPTCHA", "startpage news: CAPTCHA",
        "reuters: boh"]


def test_time_budget_stops_the_ladder() -> None:
    saved = settings.search_ladder_budget
    settings.search_ladder_budget = 0
    try:
        d, calls = _run(ONLY, _only_answers)
    finally:
        settings.search_ladder_budget = saved
    assert len(calls) == 1 and d["count"] == 1


def test_searxng_asks_web_and_news_and_reports_engines_down() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={
            "results": [{"url": "https://www.ansa.it/x", "title": "t", "content": "c",
                         "publishedDate": "2024-05-02T10:00:00"}],
            "unresponsive_engines": [["google cse", "Suspended: timeout"], ["duckduckgo", "CAPTCHA"]]})

    real = providers.httpx.AsyncClient

    class _Client(real):
        def __init__(self, **kw):
            super().__init__(transport=httpx.MockTransport(handler), **kw)

    providers.httpx.AsyncClient = _Client
    try:
        status, items, down = asyncio.run(providers._searxng_call('"Only Italia Logistics"', 10))
    finally:
        providers.httpx.AsyncClient = real
    assert status == "ok" and seen["categories"] == "general,news" and seen["language"] == "it"
    assert items[0]["data"] == "2024-05-02" and down == ["google cse: timeout", "duckduckgo: CAPTCHA"]


def test_adverse_results_first_then_credibility() -> None:
    raw = [{"url": "https://www.ansa.it/1", "adverse_query": False},
           {"url": "https://www.blogqualunque.it/2", "adverse_query": True},
           {"url": "https://www.facebook.com/3", "adverse_query": True}]
    out, removed = testate.postprocess(raw, dedup_by_domain=True, max_per_domain=1, min_credibility="none",
                                       max_results=10, exclude=testate.NON_NOTIZIE)
    assert [r["url"] for r in out] == ["https://www.blogqualunque.it/2", "https://www.ansa.it/1"] and removed == 1


def test_listing_pages_are_not_articles() -> None:
    raw = [{"url": "https://ricerca.repubblica.it/repubbliche-locali/topic/persone/t/tommaso+buscetta"},
           {"url": "https://www.ilgiorno.it/tag/only-italia-logistics"},
           {"url": "https://www.corriere.it/argomenti/mafia/"},
           {"url": "https://www.ansa.it/ricerca/ansait/search.shtml?any=buscetta"},
           {"url": "https://www.ansa.it/sito/notizie/cronaca/2024/05/02/sequestro-alla-only_123.html"},
           {"url": "https://www.rainews.it/articoli/2026/03/tag-e-intercettazioni-abc.html"},
           # l'archivio storico è fatto di articoli veri
           {"url": "https://ricerca.repubblica.it/repubblica/archivio/repubblica/1992/05/24/strage.html"}]
    out, removed = testate.postprocess(raw, dedup_by_domain=False, max_per_domain=1, min_credibility="none",
                                       max_results=10)
    assert [r["url"] for r in out] == [r["url"] for r in raw[4:]] and removed == 4, out


def test_extra_excluded_domains_from_config() -> None:
    saved = settings.search_exclude_domains
    settings.search_exclude_domains = "www.testata0.it, testata1.it"
    try:
        d, _ = _run(ONLY, _only_answers)
    finally:
        settings.search_exclude_domains = saved
    assert not any(("testata0" in r["url"] or "testata1" in r["url"]) for r in d["results"]) and d["count"] == 5


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok {fn.__name__}")
    print("TUTTI OK")
