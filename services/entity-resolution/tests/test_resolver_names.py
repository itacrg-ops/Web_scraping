"""Decisioni dei revisori sui nomi simili, usate dall'Entity Resolution: varianti
confermate (alias) e soggetti dichiarati diversi. Registro simulato, nessuna rete.

    python services/entity-resolution/tests/test_resolver_names.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import resolver  # noqa: E402
from app.config import settings  # noqa: E402

CUP = "E51B21000000001"
REGISTRY = [
    {"id": "S-1", "tipo": "persona_fisica", "denominazione": "Stroppa Andrea", "cf_piva": None,
     "cup": [CUP], "alias": [], "distinti": []},
]


def _resolve(name: str, registry: list[dict], **extra) -> dict:
    orig = resolver.get_registry
    resolver.get_registry = lambda: registry
    try:
        cognome, nome = name.split()
        return resolver.resolve({"tipo_soggetto": "persona_fisica", "cognome": cognome, "nome": nome, **extra})
    finally:
        resolver.get_registry = orig


def test_nome_simile_e_candidato_da_rivedere() -> None:
    r = _resolve("Stropp Andrea", REGISTRY)
    assert r["status"] == "needs_review" and r["candidates"][0]["id"] == "S-1", r


def test_variante_confermata_risolve_col_cup() -> None:
    reg = [{**REGISTRY[0], "alias": ["Stropp Andrea"]}]
    r = _resolve("Stropp Andrea", reg, cup=[CUP])
    assert r["status"] == "resolved" and r["matched"]["id"] == "S-1", r
    assert r["candidates"] == [] and r["confidence"] >= 0.9
    r = _resolve("Stropp Andrea", reg)                       # senza CUP: candidato forte, non risolto
    assert r["candidates"][0]["score"] == 1.0
    assert any("variante confermata" in w for w in r["warnings"]), r["warnings"]


def test_soggetto_dichiarato_diverso_non_e_candidato() -> None:
    reg = [{**REGISTRY[0], "distinti": ["Andrea Stropp"]}]   # stesso nome, ordine diverso
    r = _resolve("Stropp Andrea", reg)
    assert r["candidates"] == [] and r["status"] == "unresolved", r
    assert any("indicato come diversi" in w for w in r["warnings"])
    settings.allow_unregistered_subject = True               # esplorativo: ora può procedere
    try:
        assert _resolve("Stropp Andrea", reg)["status"] == "provvisorio"
    finally:
        settings.allow_unregistered_subject = False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
