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


def similarity(a: str, b: str, tipo: str | None = None) -> float:
    """Somiglianza 0..1 tra due nomi (parole in ordine alfabetico, poi confronto dei
    caratteri): «Stropp Andrea» / «Andrea Stroppa» ≈ 0,96."""
    ka = " ".join(sorted(subject_key(a, tipo).split()))
    kb = " ".join(sorted(subject_key(b, tipo).split()))
    if not ka or not kb:
        return 0.0
    return difflib.SequenceMatcher(None, ka, kb).ratio()


def clean_id(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())
