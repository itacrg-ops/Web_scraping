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


def check(subject: dict, text: str) -> dict:
    tnorm = _norm(text)
    tnorm_nospace = tnorm.replace(" ", "")
    name_tokens = [t for t in _norm(subject.get("denominazione", "")).split() if t not in GENERIC]
    matched: list[str] = []

    cf = re.sub(r"[^A-Z0-9]", "", (subject.get("cf_piva") or "").upper())
    if cf and cf in tnorm_nospace:
        matched.append("cf_piva")

    core_name = " ".join(name_tokens)
    if core_name and core_name in tnorm:
        matched.append("denominazione")

    distinctive = [t for t in name_tokens if len(t) >= 4]
    if distinctive and all(t in tnorm for t in distinctive):
        matched.append("token")

    return {"mentioned": bool(matched), "matched": sorted(set(matched)), "distinctive": distinctive}
