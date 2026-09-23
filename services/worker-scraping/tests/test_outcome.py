"""Test dell'esito INCOMPLETO: un guasto non deve sembrare un esito valido.

    python services/worker-scraping/tests/test_outcome.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from outcome import INCOMPLETE, apply_incomplete, incomplete_reasons  # noqa: E402

LLM = {"method": "llm_dual", "fatf_categories": ["Corruption & Bribery"]}
KEYWORD = {"method": "euristica_keyword", "fatf_categories": ["Money Laundering"],
           "fallback_reason": "llm-gateway HTTP 503"}
URLS = ["https://a.it/1", "https://b.it/2"]


def _reasons(**kw) -> list[str]:
    base = dict(search_error=None, urls=URLS, docs_with_text=2, classification=LLM, risk_feed=None)
    return incomplete_reasons(**{**base, **kw})


def test_valid_run_has_no_reasons() -> None:
    assert _reasons() == []
    # ricerca riuscita con zero articoli = esito legittimo (non incompleto)
    assert _reasons(urls=[], docs_with_text=0, classification={"method": "nessun_contenuto"}) == []


def test_search_failure_is_incomplete() -> None:
    r = _reasons(search_error="GDELT 429", urls=[], docs_with_text=0,
                 classification={"method": "nessun_contenuto"})
    assert len(r) == 1 and "ricerca articoli non riuscita (GDELT 429)" in r[0]


def test_no_content_from_sources_is_incomplete() -> None:
    r = _reasons(docs_with_text=0, classification={"method": "nessun_contenuto"})
    assert len(r) == 1 and "nessun contenuto recuperato dalle 2 fonti" in r[0]


def test_keyword_fallback_is_incomplete() -> None:
    r = _reasons(classification=KEYWORD)
    assert len(r) == 1 and "parole chiave (llm-gateway HTTP 503)" in r[0]


def test_risk_feed_error_is_incomplete_but_disabled_feed_is_not() -> None:
    r = _reasons(risk_feed={"available": False, "error": True, "provider": "crimetech",
                            "reason": "timeout"})
    assert r == ["feed di rischio crimetech non raggiungibile (timeout)"]
    assert _reasons(risk_feed={"available": False, "reason": "nessun riscontro"}) == []


def test_apply_incomplete_never_auto_closes_or_escalates() -> None:
    clean = {"ami_score": 8, "risk_level": "BASSO", "disposition": "AUTO_CHIUSO", "drivers": ["x"]}
    assert apply_incomplete(clean, []) is clean                      # nessun motivo: invariato
    out = apply_incomplete(clean, ["ricerca articoli non riuscita (rete)"])
    assert out["disposition"] == INCOMPLETE and out["risk_level"] == "N/D"
    assert out["drivers"][0].startswith("⚠ ESITO INCOMPLETO") and out["drivers"][-1] == "x"
    assert out["ami_score"] == 8                                     # AMI conservato (indicativo)
    hot = {"ami_score": 78, "risk_level": "ALTO", "disposition": "ESCALATION_I_LIVELLO", "drivers": []}
    assert apply_incomplete(hot, ["classificazione a parole chiave"])["disposition"] == INCOMPLETE


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
