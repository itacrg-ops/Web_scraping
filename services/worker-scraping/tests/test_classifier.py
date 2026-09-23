"""Test del classificatore di ripiego a keyword (precisione nel dominio FSC/MASE).

    python services/worker-scraping/tests/test_classifier.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import classifier  # noqa: E402

ML, CB, FR, OC = "Money Laundering", "Corruption & Bribery", "Fraud & Financial Crime", "Organized Crime"


def _cats(text: str) -> list[str]:
    return classifier.classify_text(text)["fatf_categories"]


def _role(text: str) -> str | None:
    return classifier.classify_text(text)["ruolo_processuale"]


def test_recycling_is_not_money_laundering() -> None:
    for t in [
        "Inaugurato il nuovo impianto di riciclo dei rifiuti plastici finanziato con fondi FSC.",
        "Nuovo impianto di riciclaggio dei rifiuti finanziato con fondi FSC.",
        "Il riciclaggio della carta a Roma Capitale cresce del 10%.",
        "Raccolta differenziata e riciclaggio: al via la bonifica dell'area.",
        "Riciclaggio degli pneumatici: creati 50 posti di lavoro.",
        "La normativa antiriciclaggio impone nuovi controlli alle banche.",
    ]:
        assert ML not in _cats(t), t


def test_money_laundering_is_detected() -> None:
    for t in [
        "L'imprenditore è indagato per riciclaggio e autoriciclaggio.",
        "Accusato di riciclaggio, ha rifiutato di rispondere al gip.",
        "Riciclaggio di denaro tramite carte di credito prepagate.",
        "Sequestro per riciclaggio a Roma.",
        "Il clan riciclava denaro in un impianto di rifiuti.",
        "Riciclaggio dei proventi del traffico illecito di rifiuti.",
    ]:
        assert ML in _cats(t), t


def test_anti_prefixed_compliance_terms_are_not_adverse() -> None:
    assert CB not in _cats("Il piano anticorruzione dell'ente è stato approvato dall'ANAC.")
    assert CB not in _cats("Autorità Nazionale Anticorruzione: nuove linee guida.")
    assert OC not in _cats("L'impresa è iscritta nella white list antimafia della Prefettura.")
    assert OC not in _cats("Rilasciata la certificazione anti-mafia.")
    # …ma le misure antimafia contro l'impresa restano avverse
    assert OC in _cats("Emessa un'interdittiva antimafia nei confronti della società.")
    assert OC in _cats("Notificata l'informazione antimafia interdittiva.")


def test_generic_false_and_investigation_words() -> None:
    assert FR not in _cats("Circolano notizie false sul cantiere.")
    assert FR in _cats("Contestato il falso in bilancio agli amministratori.")
    assert _role("Completata l'indagine geologica preliminare sull'area.") is None
    assert _role("Il direttore dei lavori è stato colpito da arresto cardiaco.") is None
    assert _role("Consultato l'archivio storico comunale.") is None


def test_classic_positives_still_detected() -> None:
    assert _cats("Arrestato per corruzione e turbativa d'asta, intascava mazzette.") == [CB]
    assert _cats("Bancarotta fraudolenta e truffa ai danni dello Stato.") == [FR]
    assert _cats("Associazione a delinquere di stampo mafioso legata alla 'ndrangheta.") == [OC]
    assert _cats("Indagine per corruzione e riciclaggio: sequestrati i beni.") == [CB, ML]
    assert _role("Il sindaco è stato condannato in primo grado.") == "condanna"
    assert _role("Chiesto il rinvio a giudizio per l'imputato.") == "rinvio_a_giudizio"
    assert _role("Il gip ha disposto l'archiviazione del procedimento.") == "archiviazione"
    assert _role("L'assessore risulta indagato dalla procura.") == "indagine_preliminare"
    assert _role("Perquisizioni della Guardia di Finanza negli uffici.") == "indagine_preliminare"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
