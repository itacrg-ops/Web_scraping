"""Test del decode/coerenza del Codice Fiscale (B7). Pytest o script:

    python services/entity-resolution/tests/test_codice_fiscale.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import codice_fiscale as cf  # noqa: E402

ROSSI = "RSSMRA80E20F205I"        # Rossi Mario, 1980-05-20, M
BIANCHI = "BNCGLI82S43H501W"      # Bianchi Giulia, 1982-11-03, F (giorno 43 = 3 + 40)


def test_decode_uomo_e_donna() -> None:
    d = cf.decode(ROSSI)
    assert d["surname_code"] == "RSS" and d["name_code"] == "MRA"
    assert d["year2"] == "80" and d["month"] == 5 and d["day"] == 20 and d["sex"] == "M"
    d = cf.decode(BIANCHI)
    assert d["sex"] == "F" and d["day"] == 3 and d["month"] == 11


def test_coerenza_ok() -> None:
    r = cf.check_consistency(ROSSI, "Mario", "Rossi", "1980-05-20")
    assert r["consistent"] is True and not r["warnings"]


def test_data_incoerente() -> None:
    r = cf.check_consistency(ROSSI, "Mario", "Rossi", "1975-03-15")
    assert r["consistent"] is False
    assert any("Anno" in w for w in r["warnings"])


def test_nome_cognome_incoerenti() -> None:
    r = cf.check_consistency(ROSSI, "Giuseppe", "Verdi", None)
    assert r["consistent"] is False
    campi = {c["campo"] for c in r["checks"] if not c["ok"]}
    assert {"nome", "cognome"} <= campi


def test_cf_malformato() -> None:
    r = cf.check_consistency("TROPPOCORTO", "Mario", "Rossi")
    assert r["valid"] is False and r["consistent"] is False


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
