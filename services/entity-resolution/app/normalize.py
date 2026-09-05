"""Normalizzazione e validazione degli identificatori italiani.

- Normalizzazione denominazioni (transliterazione, rimozione forme societarie).
- Validazione **Codice Fiscale** (carattere di controllo) e **Partita IVA**
  (checksum), gli identificatori forti su cui poggia il matching deterministico.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# Forme societarie / rumore da rimuovere dalla denominazione per il confronto.
_LEGAL_FORMS = [
    r"SOCIETA' A RESPONSABILITA' LIMITATA(?: SEMPLIFICATA)?",
    r"S\.?R\.?L\.?S?", r"S\.?P\.?A\.?", r"S\.?N\.?C\.?", r"S\.?A\.?S\.?",
    r"S\.?S\.?", r"SOC(?:IETA')?\.? ?COOP(?:ERATIVA)?\.?", r"COOP\.?",
    r"& ?C\.?", r"& ?FIGLI", r"IMPRESA INDIVIDUALE",
]
_LEGAL_RE = re.compile(r"\b(?:%s)\b" % "|".join(_LEGAL_FORMS))
_NON_ALNUM = re.compile(r"[^A-Z0-9 ]+")
_SPACES = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    s = _strip_accents((name or "").upper())
    # Suffissi "& C." / "& figli" (e compagni) prima di trattare '&'.
    s = re.sub(r"&\s*C\.?\b", " ", s)
    s = re.sub(r"&\s*FIGLI\b", " ", s)
    s = s.replace("&", " E ")
    s = s.replace(".", "")     # "S.R.L." -> "SRL": abilita il match delle forme societarie
    s = _LEGAL_RE.sub(" ", s)  # rimuove SRL/SPA/SNC/SAS/COOP/...
    s = _NON_ALNUM.sub(" ", s)  # residui di punteggiatura
    return _SPACES.sub(" ", s).strip()


def clean_id(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


# --- Partita IVA (11 cifre) ---
def valid_piva(piva: str) -> bool:
    p = clean_id(piva)
    if len(p) != 11 or not p.isdigit():
        return False
    total = 0
    for i, ch in enumerate(p[:10]):
        d = int(ch)
        if i % 2 == 1:  # posizioni pari (1-based): raddoppia
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - (total % 10)) % 10
    return check == int(p[10])


# --- Codice Fiscale (16 caratteri) ---
_CF_ODD = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
    "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13, "G": 15, "H": 17, "I": 19, "J": 21,
    "K": 2, "L": 4, "M": 18, "N": 20, "O": 11, "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14,
    "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
}
_CF_EVEN = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5, "G": 6, "H": 7, "I": 8, "J": 9,
    "K": 10, "L": 11, "M": 12, "N": 13, "O": 14, "P": 15, "Q": 16, "R": 17, "S": 18, "T": 19,
    "U": 20, "V": 21, "W": 22, "X": 23, "Y": 24, "Z": 25,
}


def valid_cf(cf: str) -> bool:
    c = clean_id(cf)
    if len(c) != 16 or not c.isalnum():
        return False
    total = 0
    for i, ch in enumerate(c[:15]):
        total += _CF_ODD[ch] if i % 2 == 0 else _CF_EVEN[ch]
    return chr(65 + total % 26) == c[15]


def valid_identifier(value: str | None) -> bool:
    """Vero se il valore è un CF (16) o una P.IVA (11) formalmente valido."""
    c = clean_id(value)
    if len(c) == 11:
        return valid_piva(c)
    if len(c) == 16:
        return valid_cf(c)
    return False


def name_similarity(a: str, b: str) -> float:
    """Similarità 0..1 su denominazioni (persone giuridiche): rimuove le forme
    societarie e confronta con token-sort + ratio."""
    ta = " ".join(sorted(normalize_name(a).split()))
    tb = " ".join(sorted(normalize_name(b).split()))
    if not ta or not tb:
        return 0.0
    return difflib.SequenceMatcher(None, ta, tb).ratio()


def normalize_person_name(name: str) -> str:
    """Normalizza nome+cognome di una persona fisica: translitterazione,
    maiuscolo, rimozione punteggiatura. NON rimuove forme societarie (un
    cognome potrebbe coincidere con un token come 'Sas'/'Coop')."""
    s = _strip_accents((name or "").upper())
    s = _NON_ALNUM.sub(" ", s)
    return _SPACES.sub(" ", s).strip()


def person_name_similarity(a: str, b: str) -> float:
    """Similarità 0..1 su nomi di persona (token-sort: l'ordine
    nome/cognome non conta)."""
    ta = " ".join(sorted(normalize_person_name(a).split()))
    tb = " ".join(sorted(normalize_person_name(b).split()))
    if not ta or not tb:
        return 0.0
    return difflib.SequenceMatcher(None, ta, tb).ratio()
