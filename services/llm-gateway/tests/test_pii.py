"""Test della redazione PII (B1). Eseguibile con pytest o come script:

    python services/llm-gateway/tests/test_pii.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import pii  # noqa: E402


def test_redige_pii_strutturate() -> None:
    text = (
        "Il RUP Mario Rossi (CF RSSMRA80E20F205I), email mario.rossi@example.it, "
        "tel. +39 06 12345678 e cell. 333 1234567, P.IVA 12345678903, "
        "IBAN IT60X0542811101000000123456, coinvolto nell'inchiesta appalti."
    )
    out, rep = pii.redact(text)
    # PII rimosse
    for leaked in ("RSSMRA80E20F205I", "mario.rossi@example.it", "12345678903",
                   "IT60X0542811101000000123456", "12345678", "1234567"):
        assert leaked not in out, f"PII non redatta: {leaked!r}"
    # placeholder presenti
    for ph in ("[CF]", "[EMAIL]", "[P.IVA]", "[IBAN]", "[TELEFONO]"):
        assert ph in out, f"placeholder mancante: {ph}"
    # report audit coerente (email+iban+cf+piva+2 telefoni = 6)
    assert rep["total"] >= 6, rep
    assert rep["by_category"].get("tel", 0) == 2, rep
    # MVP: il NOME NON è mascherato (richiede NER — B1.1)
    assert "Mario Rossi" in out


def test_preserva_non_pii() -> None:
    """Anni, importi, date e numeri di procedimento NON devono essere toccati:
    servono alla classificazione FATF."""
    text = (
        "Nel 2019 l'importo contestato è di € 2.300.000; udienza il 12/03/2024, "
        "procedimento n. 4567/2021, per oltre 500.000 euro di lavori pubblici."
    )
    out, rep = pii.redact(text)
    assert out == text, f"testo alterato: {out!r}"
    assert rep["total"] == 0, rep


def test_toggle_e_vuoto() -> None:
    assert pii.redact("")[0] == ""
    assert pii.redact("nessuna pii qui")[1]["total"] == 0


def _run() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"✔ {name}")
            except AssertionError as e:
                fails += 1
                print(f"✖ {name}: {e}")
    print(f"\n{'TUTTI OK' if not fails else str(fails) + ' FALLITI'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_run())
