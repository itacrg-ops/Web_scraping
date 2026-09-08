"""Test della mappatura feed di rischio → FATF/AMI/evidenza (funzioni pure).

    pytest services/risk-gateway/tests/test_mapping.py
    python  services/risk-gateway/tests/test_mapping.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import mapping  # noqa: E402


def test_crime_to_fatf_uses_media_vocabulary():
    assert mapping.crime_to_fatf("corruption") == "Corruption & Bribery"
    assert mapping.crime_to_fatf("Bid rigging") == "Corruption & Bribery"
    assert mapping.crime_to_fatf("tax evasion") == "Fraud & Financial Crime"
    assert mapping.crime_to_fatf("money laundering") == "Money Laundering"
    assert mapping.crime_to_fatf("organized crime") == "Organized Crime"
    assert mapping.crime_to_fatf("sanctions breach") == "Sanctions & Embargoes"
    assert mapping.crime_to_fatf("qualcosa di ignoto") is None
    assert mapping.crime_to_fatf(None) is None


def test_rating_to_severity_normalizes():
    assert mapping.rating_to_severity("HIGH") == "alta"
    assert mapping.rating_to_severity("medio") == "media"
    assert mapping.rating_to_severity("low") == "bassa"
    assert mapping.rating_to_severity("boh") is None


def test_build_assessment_aggregates_indicators_and_connections():
    raw = {
        "entity_id": "E1",
        "risk_indicators": [
            {"indicator": "Corruzione appalti", "crime_type": "corruption",
             "rating": "high", "explanation": "dettaglio"},
            {"indicator": "Reati fiscali", "crime_type": "tax", "rating": "medium"},
        ],
        "connections": [
            {"entity": "Omega S.r.l.", "entity_id": "E2", "relationship": "socio",
             "risk_flag": True, "crime_type": "organized crime", "rating": "high"},
            {"entity": "Studio X", "relationship": "consulente", "risk_flag": False},
        ],
    }
    a = mapping.build_assessment("crimetech", raw)
    assert a["available"] is True
    assert a["entity_id"] == "E1"
    # categorie FATF dedotte da indicatori + connessioni a rischio, senza duplicati
    assert a["fatf_categories"] == [
        "Corruption & Bribery", "Fraud & Financial Crime", "Organized Crime",
    ]
    # severità aggregata = massimo tra indicatori/connessioni (high -> alta)
    assert a["severity"] == "alta"
    # solo la connessione a rischio diventa evidenza strutturata
    assert len(a["evidence"]) == 1
    assert a["evidence"][0]["tipo"] == "connessione"
    assert a["evidence"][0]["entity"] == "Omega S.r.l."
    assert a["evidence"][0]["fatf_category"] == "Organized Crime"
    # driver esplicabili: sommario + un driver per indicatore + connessione a rischio
    assert any(d.startswith("Feed di rischio crimetech") for d in a["drivers"])
    assert any("Connessione a rischio" in d for d in a["drivers"])


def test_unavailable_contract_is_stable():
    u = mapping.unavailable("crimetech", "feed OFF")
    assert u["available"] is False
    assert u["reason"] == "feed OFF"
    for k in ("fatf_categories", "risk_indicators", "connections", "drivers", "evidence"):
        assert u[k] == []
    assert u["severity"] is None


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            fails += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - fails}/{len(fns)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_run())
