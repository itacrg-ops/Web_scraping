"""Nomi dei soggetti: chiave di confronto e similarità.

Servono a riconoscere lo stesso soggetto scritto in modi diversi (alert duplicati,
casi già nel dataset) e i nomi SIMILI da confermare prima di uno screening
(«Stropp Andrea» / «Stroppa Andrea»: refuso o persona diversa?).
"""
from __future__ import annotations

import difflib
import re
import unicodedata

PERSONA_FISICA = "persona_fisica"
# Forme giuridiche dopo la normalizzazione ("S.r.l." → "S R L"): non distinguono il soggetto.
_LEGAL = re.compile(
    r"\b(?:S R L S|SRLS|S R L|SRL|S P A|SPA|S N C|SNC|S A S|SAS|S C A R L|SCARL|S C P A|SCPA"
    r"|SOC COOP|SOCIETA COOPERATIVA|COOP|ONLUS|UNIPERSONALE|IN LIQUIDAZIONE)\b")
# Sotto questa similarità due nomi non si propongono come «simili».
SIMILAR_MIN = 0.85


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", s).split())


def subject_key(name: str, tipo: str | None = None) -> str:
    """Chiave dello stesso soggetto: maiuscole, senza accenti né punteggiatura; per le
    imprese senza forma giuridica («ACME S.r.l.» = «Acme srl»), per le persone in
    qualunque ordine («Rossi Mario» = «Mario Rossi»)."""
    s = _norm(name)
    if tipo == PERSONA_FISICA:
        return " ".join(sorted(s.split()))
    return " ".join(_LEGAL.sub(" ", s).split()) or s


def _weakest_word(ta: list[str], tb: list[str]) -> float:
    """Somiglianza della coppia di parole peggiore (ogni parola del nome più corto con
    la più simile dell'altro): stessa regola dell'Entity Resolution."""
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    free, worst = list(long_), 1.0
    for w in sorted(short, key=len, reverse=True):
        scores = [1.0 if w == x else difflib.SequenceMatcher(None, w, x).ratio() for x in free]
        if not scores:
            return 0.0
        i = max(range(len(scores)), key=scores.__getitem__)
        worst = min(worst, scores[i])
        free.pop(i)
    return worst


def similarity(a: str, b: str, tipo: str | None = None) -> float:
    """Somiglianza 0..1 tra due nomi (parole in ordine alfabetico, poi confronto dei
    caratteri): «Stropp Andrea» / «Andrea Stroppa» ≈ 0,92. Per le persone conta anche
    la parola meno simile: un nome di battesimo in comune non rende simili «Cocina
    Salvatore» e «Riina Salvatore»."""
    ta, tb = sorted(subject_key(a, tipo).split()), sorted(subject_key(b, tipo).split())
    if not ta or not tb:
        return 0.0
    full = difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return min(full, _weakest_word(ta, tb)) if tipo == PERSONA_FISICA else full


def clean_id(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())
