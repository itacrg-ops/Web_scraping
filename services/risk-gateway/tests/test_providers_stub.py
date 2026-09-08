"""Test del dispatch provider e delle **guardie anti-egress** dello stub.

Garantisce che:
  - feed OFF (default) → non disponibile, nessun provider;
  - `mock` → assessment disponibile e mappato (collaudo offline);
  - `crimetech` → in ogni configurazione priva di (live + chiave + reconcile)
    ritorna `available:false` **senza** costruire/chiamare l'URL esterno.

    pytest services/risk-gateway/tests/test_providers_stub.py
    python  services/risk-gateway/tests/test_providers_stub.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import crimetech, providers  # noqa: E402
from app.config import settings  # noqa: E402

SUBJECT = {"tipo_soggetto": "persona_giuridica", "denominazione": "ACME S.r.l.",
           "cf_piva": "00743110157"}


def _reset():
    settings.risk_provider = ""
    settings.crimetech_live = False
    settings.crimetech_api_key = ""
    settings.crimetech_dataset_id = ""


def test_feed_off_by_default():
    _reset()
    a = providers.assess(SUBJECT)
    assert a["available"] is False
    assert a["provider"] == "nessuno"


def test_mock_provider_maps_profile():
    _reset()
    settings.risk_provider = "mock"
    a = providers.assess(SUBJECT)
    assert a["available"] is True
    assert a["provider"] == "mock"
    assert "Corruption & Bribery" in a["fatf_categories"]
    assert a["severity"] == "alta"          # connessione "organized crime" high
    assert a["drivers"] and a["evidence"]
    _reset()


def test_crimetech_stub_no_egress_when_live_off():
    _reset()
    settings.risk_provider = "crimetech"
    a = providers.assess(SUBJECT)
    assert a["available"] is False
    assert "stub" in (a["reason"] or "")
    assert "live disabilitato" in (a["reason"] or "")
    _reset()


def test_crimetech_stub_guard_key_missing():
    _reset()
    settings.risk_provider = "crimetech"
    settings.crimetech_live = True          # live ON ma niente chiave
    a = providers.assess(SUBJECT)
    assert a["available"] is False
    assert "chiave assente" in (a["reason"] or "")
    _reset()


def test_crimetech_stub_stops_at_reconcile():
    """Con tutte le guardie soddisfatte, si ferma comunque alla riconciliazione
    (endpoint reconcile non integrato): nessuna chiamata alle connessioni."""
    _reset()
    settings.risk_provider = "crimetech"
    settings.crimetech_live = True
    settings.crimetech_api_key = "dummy-not-a-real-key"
    settings.crimetech_dataset_id = "ds-test"
    a = providers.assess(SUBJECT)
    assert a["available"] is False
    assert "riconciliata" in (a["reason"] or "")
    # e il reconcile è davvero uno stub che non risolve
    assert crimetech._resolve_entity_id(SUBJECT) is None
    _reset()


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
