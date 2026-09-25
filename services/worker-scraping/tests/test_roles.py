"""Ruoli della persona negli articoli (cariche PEP, ruoli politici e aziendali): il ruolo
conta solo se è scritto accanto al nome, nella stessa frase.

    python services/worker-scraping/tests/test_roles.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import roles  # noqa: E402

ROSSI = {"tipo_soggetto": "persona_fisica", "denominazione": "Rossi Mario"}


def _r(text: str) -> list[tuple]:
    return [(r["ruolo"], r["tipo"], r["pep"]) for r in roles.extract(ROSSI, text)]


def test_role_before_or_after_the_name() -> None:
    assert _r("Il sindaco di Roma Mario Rossi ha firmato.") == [("sindaco di Roma", "sindaco", "verifica")]
    assert _r("Mario Rossi, amministratore delegato di Sogei, è indagato.") == [
        ("amministratore delegato di Sogei", "amministratore delegato", None)]
    assert _r("Mario Rossi è il direttore generale dell'Asl Roma 1.") == [
        ("direttore generale dell'Asl Roma 1", "direttore generale di azienda sanitaria", "si")]
    assert _r("Mario Rossi, 58 anni, consigliere comunale di Latina, è indagato.") == [
        ("consigliere comunale di Latina", "consigliere comunale", None)]


def test_pep_offices_and_former_offices() -> None:
    assert _r("Lo ha dichiarato l'ex ministro Mario Rossi.") == [("ex ministro", "ministro", "si")]
    assert _r("Mario Rossi, già senatore, è stato ascoltato.") == [("ex senatore", "senatore", "si")]
    assert _r("Il presidente della Regione Lazio Mario Rossi ha parlato.") == [
        ("presidente della Regione Lazio", "presidente della Regione", "si")]
    assert _r("L'onorevole Mario Rossi ha votato.") == [("onorevole", "deputato", "si")]
    assert roles.is_pep(roles.extract(ROSSI, "Il sindaco Mario Rossi"))
    assert not roles.is_pep(roles.extract(ROSSI, "Il consigliere comunale Mario Rossi"))


def test_abbreviations_only_in_capitals() -> None:
    assert _r("Mario Rossi (AD di Acme S.p.A.) non commenta.") == [
        ("AD di Acme S.p.A.", "amministratore delegato", None)]
    assert _r("Mario Rossi, CEO della Alfa Beta Spa, si è dimesso.")[0][1] == "amministratore delegato"
    assert _r("Ad esempio Mario Rossi ha pagato.") == []


def test_role_must_be_next_to_the_name() -> None:
    assert _r("Il sindaco ha incontrato i cittadini. Mario Rossi, imprenditore, c'era.") == [
        ("imprenditore", "imprenditore", None)]
    assert _r("Mario Bianchi, sindaco di Latina, e Mario Rossi sono indagati.") == []
    assert _r("In generale, Mario Rossi ha rispettato le regole.") == []


def test_corporate_auditor_is_not_a_mayor() -> None:
    assert _r("Il sindaco effettivo Mario Rossi ha firmato.") == [
        ("sindaco effettivo", "sindaco (collegio sindacale)", None)]


def test_summary_across_articles() -> None:
    a = roles.extract(ROSSI, "Il sindaco di Roma Mario Rossi. Mario Rossi, imprenditore.")
    b = roles.extract(ROSSI, "Mario Rossi, sindaco di Roma, ha parlato.")
    s = roles.summarize([a, b])
    assert [(x["ruolo"], x["articoli"]) for x in s] == [("sindaco di Roma", 2), ("imprenditore", 1)]
    assert roles.extract({"tipo_soggetto": "persona_giuridica", "denominazione": "Acme"}, "Il sindaco Acme") == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
