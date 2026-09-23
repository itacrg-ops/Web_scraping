"""Test: un guasto della ricerca NON deve sembrare "nessun articolo trovato".

`/v1/search` valorizza `error` solo se la ricerca è FALLITA (provider in errore,
429, non configurato; in fan-out: tutti i provider falliti). Le note informative
(es. query allargata) e i guasti parziali non sono errori.

    python services/search-gateway/tests/test_provider_errors.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app import main, providers  # noqa: E402
from app.config import settings  # noqa: E402

SUBJECT = {"tipo_soggetto": "persona_giuridica", "denominazione": "ACME Costruzioni S.r.l."}


def _search(provider: str, gdelt_status: str = "error") -> dict:
    """POST /v1/search con il provider indicato; GDELT simulato (nessuna rete)."""
    async def fake_gdelt_call(query_str, max_results, timespan):
        if gdelt_status == "ok":
            return "ok", [{"url": "https://www.ansa.it/a", "title": "t", "domain": "ansa.it",
                           "provider": "gdelt"}]
        return gdelt_status, None

    saved = (settings.search_provider, providers._gdelt_call, settings.brave_api_key)
    settings.search_provider, providers._gdelt_call, settings.brave_api_key = provider, fake_gdelt_call, ""
    main._cache.clear()
    try:
        async def _call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                         base_url="http://t") as c:
                return await c.post("/v1/search", json={"subject": SUBJECT, "max_results": 3})
        r = asyncio.run(_call())
        assert r.status_code == 200, r.text
        return r.json()
    finally:
        settings.search_provider, providers._gdelt_call, settings.brave_api_key = saved


def test_single_provider_failure_is_reported_as_error() -> None:
    d = _search("gdelt", gdelt_status="error")
    assert d["count"] == 0 and d["error"] and "GDELT" in d["error"]


def test_unconfigured_provider_is_an_error() -> None:
    d = _search("brave")
    assert d["error"] and "BRAVE_API_KEY" in d["error"]


def test_successful_search_has_no_error() -> None:
    d = _search("mock")
    assert d["error"] is None and d["count"] > 0
    d = _search("gdelt", gdelt_status="ok")
    assert d["error"] is None and d["count"] == 1


def test_fanout_error_only_if_all_providers_fail() -> None:
    d = _search("gdelt,brave", gdelt_status="error")        # entrambi falliti
    assert d["error"] and "gdelt" in d["error"] and "brave" in d["error"]
    d = _search("mock,brave")                                # uno fallito, uno ok
    assert d["error"] is None and d["count"] > 0
    assert d["note"] and "brave" in d["note"]               # il guasto parziale resta visibile


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
