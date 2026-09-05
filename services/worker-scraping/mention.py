"""Verifica di menzione del soggetto nell'evidenza (anti falsa attribuzione).

Controlla che il soggetto (CF/P.IVA o denominazione/token distintivi) compaia
nel **testo completo** dell'evidenza. Complemento dell'anti-omonimia: evita di
attribuire una notizia a un soggetto che non vi è citato. Qui è usata in modo
**non bloccante** (annota un warning), configurabile come bloccante.
TODO: NER e alias per una copertura più robusta.
"""
from __future__ import annotations

import re
import unicodedata

# Parole generiche che da sole non identificano un soggetto.
GENERIC = {
    "SRL", "SRLS", "SPA", "SNC", "SAS", "SS", "COOP", "COOPERATIVA", "SOCIETA",
    "GRUPPO", "GROUP", "HOLDING", "IMPRESA", "IMPRESE", "COSTRUZIONI",
    "INFRASTRUTTURE", "SERVIZI", "ITALIA", "ITALIANA", "GENERALE", "GENERALI",
    "LAVORI", "EDILE", "EDILIZIA", "IMPIANTI", "GESTIONE", "GESTIONI",
    "CONSORZIO", "ENERGIA", "AMBIENTE", "GLOBAL", "INTERNATIONAL",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _check_person(subject: dict, tnorm: str, tnorm_nospace: str, matched: list[str]) -> list[str]:
    """Menzione di una persona fisica: servono nome E cognome (in qualunque
    ordine) oppure il CF. Un solo nome/cognome non basta (troppo comune)."""
    nome = _norm(subject.get("nome", ""))
    cognome = _norm(subject.get("cognome", ""))
    # In assenza di nome/cognome espliciti, usa i token della denominazione ("Cognome Nome").
    if not (nome or cognome):
        toks = _norm(subject.get("denominazione", "")).split()
        cognome = toks[0] if toks else ""
        nome = " ".join(toks[1:]) if len(toks) > 1 else ""

    full_present = bool(nome) and bool(cognome) and (nome in tnorm) and (cognome in tnorm)
    if full_present:
        matched.append("nome_cognome")
    distinctive = [t for t in (nome.split() + cognome.split()) if len(t) >= 3]
    return distinctive


def _check_entity(subject: dict, tnorm: str, matched: list[str]) -> list[str]:
    """Menzione di una persona giuridica: denominazione o token distintivi
    (escludendo le parole generiche)."""
    name_tokens = [t for t in _norm(subject.get("denominazione", "")).split() if t not in GENERIC]
    core_name = " ".join(name_tokens)
    if core_name and core_name in tnorm:
        matched.append("denominazione")
    distinctive = [t for t in name_tokens if len(t) >= 4]
    if distinctive and all(t in tnorm for t in distinctive):
        matched.append("token")
    return distinctive


def check(subject: dict, text: str) -> dict:
    tnorm = _norm(text)
    tnorm_nospace = tnorm.replace(" ", "")
    matched: list[str] = []

    cf = re.sub(r"[^A-Z0-9]", "", (subject.get("cf_piva") or "").upper())
    if cf and cf in tnorm_nospace:
        matched.append("cf_piva")

    if (subject.get("tipo_soggetto") or "persona_giuridica") == "persona_fisica":
        distinctive = _check_person(subject, tnorm, tnorm_nospace, matched)
    else:
        distinctive = _check_entity(subject, tnorm, matched)

    return {"mentioned": bool(matched), "matched": sorted(set(matched)), "distinctive": distinctive}
