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
    resolver.get_registry = lambda fresh=False: registry
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


def test_stesso_nome_di_battesimo_non_rende_candidati() -> None:
    # «Cocina Salvatore» non è a registro: «Riina Salvatore» e «Costa Salvatore» non sono
    # suoi omonimi (prima: candidati per il solo «Salvatore» → ambiguous, screening fermo)
    reg = [{"id": f"S-{i}", "tipo": "persona_fisica", "denominazione": d, "cf_piva": None, "cup": [],
            "alias": [], "distinti": []}
           for i, d in enumerate(["Riina Salvatore", "Costa Salvatore", "Coco Salvatore"])]
    r = _resolve("Cocina Salvatore", reg)
    assert r["status"] == "unresolved" and r["candidates"] == [], r
    # un refuso vero resta un candidato da rivedere
    reg.append({**reg[0], "id": "S-9", "denominazione": "Cucina Salvatore"})
    r = _resolve("Cocina Salvatore", reg)
    assert r["status"] == "needs_review" and [c["id"] for c in r["candidates"]] == ["S-9"], r


def test_scelta_del_revisore_risolve() -> None:
    # caso «Da disambiguare» → il revisore indica il candidato giusto → screening ripetuto
    reg = [{**REGISTRY[0], "id": "S-7", "denominazione": "Cucina Salvatore"}]
    r = _resolve("Cocina Salvatore", reg, subject_id="S-7")
    assert r["status"] == "resolved" and r["method"] == "scelta_revisore", r
    assert r["matched"]["id"] == "S-7" and r["confidence"] == 1.0
    assert any("indicata dal revisore" in w for w in r["warnings"])


def test_soggetto_appena_inserito_rilegge_il_registro() -> None:
    # «Aggiungi al registro e ripeti»: la cache dell'ER (30 s) non ha ancora il soggetto
    new = {**REGISTRY[0], "id": "S-8", "denominazione": "Cocina Salvatore"}
    orig = resolver.get_registry
    resolver.get_registry = lambda fresh=False: REGISTRY + [new] if fresh else REGISTRY
    try:
        r = resolver.resolve({"tipo_soggetto": "persona_fisica", "cognome": "Cocina", "nome": "Salvatore",
                              "subject_id": "S-8"})
    finally:
        resolver.get_registry = orig
    assert r["method"] == "scelta_revisore" and r["matched"]["id"] == "S-8", r


def test_scelta_del_revisore_non_applicata() -> None:
    reg = [{**REGISTRY[0], "id": "S-7", "denominazione": "Cucina Salvatore", "cf_piva": "CCNSVT80A01H501U"}]
    # soggetto non più a registro: percorso normale, con avviso
    r = _resolve("Cocina Salvatore", reg, subject_id="S-404")
    assert r["method"] != "scelta_revisore" and r["status"] == "needs_review", r
    assert any("non è più nel registro" in w for w in r["warnings"])
    # CF indicato diverso da quello del soggetto scelto
    r = _resolve("Cocina Salvatore", reg, subject_id="S-7", cf_piva="RSSMRA80A01H501U")
    assert r["method"] != "scelta_revisore" and not r["resolved"], r
    assert any("scelta del revisore non applicata" in w for w in r["warnings"])
    # nome diverso: il soggetto era rimasto indicato nel modulo
    r = _resolve("Rossi Mario", reg, subject_id="S-7")
    assert r["method"] != "scelta_revisore" and not r["resolved"], r
    assert any("né una sua variante" in w for w in r["warnings"])
    # ... ma una variante confermata vale (es. nuova ragione sociale, refuso)
    r = _resolve("Rossi Mario", [{**reg[0], "alias": ["Mario Rossi"]}], subject_id="S-7")
    assert r["method"] == "scelta_revisore", r
    # tipo di soggetto diverso (una società scelta per una persona)
    r = _resolve("Cocina Salvatore", [{**reg[0], "tipo": "persona_giuridica"}], subject_id="S-7")
    assert r["method"] != "scelta_revisore" and not r["resolved"], r
    assert any("altro tipo di soggetto" in w for w in r["warnings"])


ACME = {"id": "S-2", "tipo": "persona_giuridica", "denominazione": "ACME Costruzioni S.r.l.",
        "cf_piva": "00743110157", "cup": [], "alias": [], "distinti": []}


def _resolve_pg(denominazione: str, registry: list[dict], cf: str = "00743110157") -> dict:
    orig = resolver.get_registry
    resolver.get_registry = lambda fresh=False: registry
    try:
        return resolver.resolve({"tipo_soggetto": "persona_giuridica", "denominazione": denominazione, "cf_piva": cf})
    finally:
        resolver.get_registry = orig


def test_piva_di_un_altra_impresa_va_in_revisione() -> None:
    # es. la P.IVA di esempio rimasta nel modulo di screening
    r = _resolve_pg("Only Italia Logistics S.r.l.", [ACME])
    assert r["status"] == "needs_review" and r["method"] == "conflitto_CF_nome" and r["matched"] is None, r
    assert r["candidates"][0]["id"] == "S-2" and any("ACME Costruzioni" in w for w in r["warnings"])


def test_piva_con_nome_compatibile_resta_deterministica() -> None:
    for name in ("ACME Costruzioni", "Acme S.p.A.", "ACME COSTRUZIONI SRL"):
        r = _resolve_pg(name, [ACME])
        assert r["status"] == "resolved" and r["method"] == "deterministico_CF_PIVA", (name, r)
    # nome precedente registrato come variante: stessa impresa
    r = _resolve_pg("Beta Logistica Srl", [{**ACME, "alias": ["Beta Logistica"]}])
    assert r["status"] == "resolved", r
    # le parole comuni non bastano: "Costruzioni Rossi" non è ACME Costruzioni
    r = _resolve_pg("Costruzioni Rossi", [ACME])
    assert r["method"] == "conflitto_CF_nome", r


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
