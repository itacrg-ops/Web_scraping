"""Test del riconoscimento del soggetto negli articoli (parole intere, non sottostringhe).

    python services/worker-scraping/tests/test_mention.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import anagraphics  # noqa: E402
import mention  # noqa: E402

ANNA = {"tipo_soggetto": "persona_fisica", "nome": "Anna", "cognome": "Rossi"}
TRON = {"tipo_soggetto": "persona_giuridica", "denominazione": "Tron Group Holding S.r.l."}
ACME = {"tipo_soggetto": "persona_giuridica", "denominazione": "ACME Costruzioni S.r.l."}
BETA = {"tipo_soggetto": "persona_giuridica", "denominazione": "Beta Infrastrutture S.p.A."}


def _m(subject: dict, text: str) -> bool:
    return mention.check(subject, text)["mentioned"]


def test_person_needs_whole_adjacent_name() -> None:
    assert not _m(ANNA, "Giovanna Rossini, assessora, ha presentato il progetto.")
    assert not _m(ANNA, "Hanno parlato Anna Bianchi e Luca Rossi.")   # due persone diverse
    assert _m(ANNA, "L'assessora Anna Rossi ha presentato il progetto.")
    assert _m(ANNA, "ROSSI Anna, 45 anni, è indagata.")               # ordine inverso
    assert mention.check(ANNA, "Anna Rossi indagata")["matched"] == ["nome_cognome"]


def test_person_compound_names_and_denominazione_fallback() -> None:
    mg = {"tipo_soggetto": "persona_fisica", "nome": "Maria Grazia", "cognome": "De Luca"}
    assert _m(mg, "La dottoressa Maria Grazia De Luca è stata ascoltata.")
    assert _m(mg, "De Luca Maria Grazia, dirigente.")
    assert not _m(mg, "Maria De Luca, omonima.")                      # nome incompleto
    rossi = {"tipo_soggetto": "persona_fisica", "denominazione": "Rossi Mario"}
    assert _m(rossi, "Mario Rossi è il RUP dell'intervento.")


def test_full_name_only_tries_every_split() -> None:
    # solo "Cognome Nome" (screening passati, rivalutazione): dove finisce il cognome?
    md = {"tipo_soggetto": "persona_fisica", "denominazione": "Messina Denaro Matteo"}
    assert _m(md, "Sequestro al tesoro di Matteo Messina Denaro.")
    assert _m(md, "MESSINA DENARO Matteo, latitante.")
    ep = {"tipo_soggetto": "persona_fisica", "denominazione": "Errante Parrino Paolo Aurelio"}
    assert _m(ep, "Arrestato Paolo Aurelio Errante Parrino, ex dirigente.")
    assert not _m(md, "Matteo Messina, assessore, e il signor Denaro.")   # parole sparse


def test_surname_particles_joined_or_separated() -> None:
    joined = {"tipo_soggetto": "persona_fisica", "nome": "Ciro", "cognome": "DiMeglio"}
    assert _m(joined, "Arrestato l'ex ad Ciro Di Meglio.")
    apart = {"tipo_soggetto": "persona_fisica", "nome": "Ciro", "cognome": "Di Meglio"}
    assert _m(apart, "Arrestato l'ex ad Ciro DiMeglio.")


def test_two_letter_company_needs_company_usage() -> None:
    qe = {"tipo_soggetto": "persona_giuridica", "denominazione": "Qè S.r.l."}
    assert _m(qe, "Sequestro alla Qè S.r.l. di Milano.")
    assert _m(qe, "Indagati i vertici della società Qè.")
    assert not _m(qe, "Il Qè dei vertici.")                              # da solo è ambiguo


def test_tax_id_is_enough() -> None:
    cf = {**ANNA, "cf_piva": "RSSNNA80A41H501X"}
    assert mention.check(cf, "Codice fiscale RSSNNA80A41H501X")["matched"] == ["cf_piva"]


def test_entity_short_name_is_not_a_substring() -> None:
    assert not _m(TRON, "Crescono gli investimenti nel settore dell'elettronica.")
    assert not _m(TRON, "Il trono del re è stato restaurato.")
    assert _m(TRON, "La Tron ha vinto l'appalto per la nuova scuola.")
    assert mention.check(TRON, "La Tron ha vinto")["matched"] == ["denominazione_breve"]


def test_entity_common_word_needs_capital_letter() -> None:
    assert not _m(ACME, "La crisi ha raggiunto l'acme nel 2020.")
    assert not _m(BETA, "Il software è ancora in versione beta.")
    assert _m(BETA, "La Beta ha consegnato i lavori.")


def test_entity_full_name_with_legal_form() -> None:
    assert _m(ACME, "Perquisizioni alla Acme Costruzioni S.r.l. di Roma.")
    assert _m(ACME, "Perquisizioni alla ACME Costruzioni Srl di Roma.")     # forma senza punti
    assert _m(BETA, "Beta Infrastrutture S.p.A. ha vinto la gara.")
    assert not _m(ACME, "Sanzionata la ACMEX Spa.")


def test_entity_longer_company_name_is_another_company() -> None:
    # "ACME Costruzioni Generali S.r.l." è un'altra società (anche nel registro demo)
    assert not _m(ACME, "Indagata la ACME Costruzioni Generali S.r.l.")
    gen = {"tipo_soggetto": "persona_giuridica", "denominazione": "ACME Costruzioni Generali S.r.l."}
    assert _m(gen, "Indagata la ACME Costruzioni Generali S.r.l.")


def test_one_word_company_needs_company_usage() -> None:
    # "Vita S.r.l.": la parola da sola è quasi sempre la parola comune
    vita = {"tipo_soggetto": "persona_giuridica", "denominazione": "Vita S.r.l."}
    assert not _m(vita, "La vita in città è cambiata dopo la pandemia.")
    assert not _m(vita, "Vita e lavoro: un convegno a Roma.")            # maiuscola solo a inizio frase
    assert mention.check(vita, "Perquisizioni alla Vita Srl di Bologna.")["matched"] == ["denominazione"]
    assert _m(vita, "Indagati i vertici della Vita S.r.l.; per i soci la vita cambia.")
    assert _m(vita, "Sequestro ai danni della società Vita, attiva nella logistica.")
    # nome proprio a metà frase, mai in minuscolo → nome breve
    assert mention.check(vita, "Il contratto con la Vita è stato annullato.")["matched"] == ["denominazione_breve"]
    assert not _m(vita, "Il contratto con la Vita è stato annullato: una vita di attese.")


def test_multi_word_company_is_a_proper_name() -> None:
    nv = {"tipo_soggetto": "persona_giuridica", "denominazione": "Nuova Vita S.r.l."}
    assert not _m(nv, "Dopo il trasferimento è iniziata una nuova vita.")
    assert _m(nv, "La Nuova Vita ha ottenuto l'appalto.")


def test_context_uses_whole_words() -> None:
    subj = {**ANNA, "localita": "Roma", "ruolo": "RUP"}
    assert mention.check(subj, "Anna Rossi, in vacanza in Romania.")["context"] == []
    assert set(mention.check(subj, "Anna Rossi, RUP del Comune di Roma.")["context"]) == {"localita", "ruolo"}


def test_birthplace_whole_words_and_conflict() -> None:
    subj = {**ANNA, "luogo_nascita": "Roma"}
    assert anagraphics.corroborate(subj, "Anna Rossi, nata a Roma.")["status"] == "confermato"
    assert anagraphics.corroborate(subj, "Anna Rossi, nata a Romano di Lombardia.")["status"] == "discordante"
    assert anagraphics.corroborate(subj, "Anna Rossi, nata a Napoli.")["status"] == "discordante"
    reggio = {**ANNA, "luogo_nascita": "Reggio nell'Emilia"}
    assert anagraphics.corroborate(reggio, "Anna Rossi, nata a Reggio Emilia.")["status"] == "confermato"
    sgr = {**ANNA, "luogo_nascita": "San Giovanni Rotondo"}   # la regex cattura 2 parole
    assert anagraphics.corroborate(sgr, "Anna Rossi, nata a San Giovanni Rotondo.")["status"] == "confermato"


def test_ner_helpers_use_whole_tokens() -> None:
    assert not mention.person_in(mention.tokens("Giovanna Rossini"), ANNA)
    assert mention.person_in(mention.tokens("Anna Rossi"), ANNA)
    assert mention.org_matches("ACME Costruzioni S.r.l.", "Acme Costruzioni")
    assert not mention.org_matches("ACME Costruzioni S.r.l.", "ACMEX")
    assert not mention.org_matches("Beta Infrastrutture", "Infrastrutture")   # solo parola generica


def test_near_variants_only_when_exact_name_missing() -> None:
    # refuso nel nome inserito: gli articoli citano il nome giusto → proposto come variante
    pf = {"tipo_soggetto": "persona_fisica", "denominazione": "Stropp Andrea"}
    res = mention.check(pf, "Tra gli indagati Andrea Stroppa, consulente.")
    assert res["mentioned"] is False and res["variants"] == ["Andrea Stroppa"], res
    # nome esatto presente: nessuna variante (sarebbe rumore)
    ok = mention.check({"tipo_soggetto": "persona_fisica", "denominazione": "Stroppa Andrea"},
                       "Andrea Stroppa e Andrea Stroppi")
    assert ok["mentioned"] is True and ok["variants"] == []
    # nomi corti e comuni: Rossi/Rosso, Mario/Maria sono di solito persone diverse
    common = mention.check({"tipo_soggetto": "persona_fisica", "denominazione": "Rossi Mario"},
                           "Mario Rosso e Maria Rossi")
    assert common["variants"] == [], common
    # cognome con particella scritto diverso: «DeMeglio» ≈ «Di Meglio» (nome in qualsiasi ordine)
    for name in ("Ciro DeMeglio", "DeMeglio Ciro"):
        dm = mention.check({"tipo_soggetto": "persona_fisica", "denominazione": name},
                           "Arrestati l'ex ad Ciro Di Meglio e l'ex dg Carleo.")
        assert dm["mentioned"] is False and dm["variants"] == ["Ciro Di Meglio"], dm
    near = mention.check({"tipo_soggetto": "persona_fisica", "denominazione": "Rossi Mario"},
                         "Il sindaco Mario Rossini e Luca Rossi.")
    assert near["variants"] == [], near
    # impresa: nome distintivo con una lettera diversa, maiuscolo come nome proprio
    pg = mention.check({"tipo_soggetto": "persona_giuridica", "denominazione": "Italware S.r.l."},
                       "La Italwere ha vinto; l'italwere minuscolo no")
    assert pg["variants"] == ["Italwere"], pg


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
