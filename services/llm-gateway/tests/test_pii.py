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


def test_redazione_nomi_persona() -> None:
    # B1.1: soggetto → [SOGGETTO], terzi → [PERSONA] (con NER simulata)
    text = "Mario Rossi ha corrotto Luca Bianchi. Rossi risulta indagato."
    out, c = pii.redact_persons(text, subject_name="Rossi Mario",
                                ner_persons=["Mario Rossi", "Luca Bianchi", "Rossi"])
    assert "Mario Rossi" not in out and "Luca Bianchi" not in out
    assert "[SOGGETTO]" in out and "[PERSONA]" in out
    assert c["soggetto"] >= 1 and c["persona"] >= 1


def test_redazione_soggetto_senza_ner() -> None:
    # senza NER: almeno il nome noto del soggetto viene pseudonimizzato
    out, c = pii.redact_persons("Il RUP Rossi Mario è indagato.", subject_name="Rossi Mario")
    assert "[SOGGETTO]" in out and c["soggetto"] == 1


def test_stesso_nome_di_battesimo_non_e_il_soggetto() -> None:
    # Bug: bastava una parola in comune. "Mario Verdi" diventava [SOGGETTO] per il
    # soggetto "Rossi Mario" e il modello gli attribuiva l'indagine di un altro.
    text = "La ditta di Mario Rossi ha vinto l'appalto. Indagato Mario Verdi per turbativa."
    out, c = pii.redact_persons(text, subject_name="Rossi Mario", ner_persons=["Mario Rossi", "Mario Verdi"])
    assert out == "La ditta di [SOGGETTO] ha vinto l'appalto. Indagato [PERSONA] per turbativa.", out
    assert c == {"soggetto": 1, "persona": 1}


def test_stesso_cognome_non_e_il_soggetto() -> None:
    text = "Minacce a Sigfrido Ranucci. Arrestato Mario Bianchi, accusato da Mario Ranucci."
    out, _ = pii.redact_persons(text, subject_name="Ranucci Sigfrido",
                                ner_persons=["Sigfrido Ranucci", "Mario Bianchi", "Mario Ranucci"])
    assert out == "Minacce a [SOGGETTO]. Arrestato [PERSONA], accusato da [PERSONA].", out


def test_riferimenti_parziali_al_soggetto() -> None:
    # solo cognome, iniziale + cognome, nome completo con un secondo nome
    for mention in ("Ranucci", "S. Ranucci", "Sigfrido Ranucci", "Sigfrido Maria Ranucci"):
        out, c = pii.redact_persons(f"Parla {mention}.", subject_name="Ranucci Sigfrido",
                                    ner_persons=[mention])
        assert out == "Parla [SOGGETTO].", (mention, out)
    # iniziale che non corrisponde: è un'altra persona
    out, _ = pii.redact_persons("Parla M. Ranucci.", subject_name="Ranucci Sigfrido",
                                ner_persons=["M. Ranucci"])
    assert out == "Parla [PERSONA].", out


def test_nome_con_refuso_non_viene_indovinato() -> None:
    # "Stropp Andrea" (refuso) non è "Andrea Stroppa": meglio nessun [SOGGETTO] che uno sbagliato
    out, c = pii.redact_persons("Perquisito Andrea Stroppa.", subject_name="Stropp Andrea",
                                ner_persons=["Andrea Stroppa"])
    assert out == "Perquisito [PERSONA]." and c["soggetto"] == 0, out


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
