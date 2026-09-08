"""Test B7 sul resolver: disambiguazione per CUP + blend embedding.

Usa il registro di **fallback** in-memory (nessuna rete). Eseguibile con pytest o
come script:  python services/entity-resolution/tests/test_resolver_b7.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import resolver, semantic  # noqa: E402
from app.config import settings  # noqa: E402

# CUP dei due omonimi "Rossi Mario" nel seed/fallback.
CUP_ROSSI_1 = "E51B21000000001"   # R-ROSSI-1 (RUP)
CUP_ROSSI_2 = "G29J24000000003"   # R-ROSSI-2


def _rossi(**extra) -> dict:
    return {"tipo_soggetto": "persona_fisica", "nome": "Mario", "cognome": "Rossi", **extra}


def test_cup_disambigua_omonimo() -> None:
    r = resolver.resolve(_rossi(cup=[CUP_ROSSI_2]))
    assert r["status"] == "resolved", r
    assert (r["matched"] or {}).get("id") == "R-ROSSI-2"
    assert r["method"] == "probabilistico_nome_CUP"

    r = resolver.resolve(_rossi(cup=[CUP_ROSSI_1]))
    assert (r["matched"] or {}).get("id") == "R-ROSSI-1"


def test_cup_non_pertinente_resta_ambiguo() -> None:
    r = resolver.resolve(_rossi(cup=["Z99Z99000000000"]))
    assert r["status"] == "ambiguous", r


def test_senza_cup_invariato() -> None:
    # comportamento pre-B7: due omonimi, nessun discriminante → ambiguous
    assert resolver.resolve(_rossi())["status"] == "ambiguous"


def test_cup_disattivabile() -> None:
    settings.allow_cup_disambiguation = False
    try:
        assert resolver.resolve(_rossi(cup=[CUP_ROSSI_2]))["status"] == "ambiguous"
    finally:
        settings.allow_cup_disambiguation = True


def test_embedding_blend_e_fallback() -> None:
    orig = semantic.similarities
    settings.use_embeddings = True
    try:
        semantic.similarities = lambda q, c: [1.0] + [0.0] * (len(c) - 1)
        r = resolver.resolve({"tipo_soggetto": "persona_giuridica", "denominazione": "XYZ inesistente"})
        assert any("embedding" in w.lower() for w in r["warnings"]), r["warnings"]
        # fallback: None → nessun blend, nessun warning embedding
        semantic.similarities = lambda q, c: None
        r = resolver.resolve({"tipo_soggetto": "persona_giuridica", "denominazione": "XYZ inesistente"})
        assert not any("embedding" in w.lower() for w in r["warnings"])
    finally:
        semantic.similarities = orig
        settings.use_embeddings = False


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
