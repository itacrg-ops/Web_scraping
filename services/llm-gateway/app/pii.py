"""Redazione PII prima dell'invio del testo all'LLM (compliance GDPR / AI Act).

Minimizzazione dei dati personali di **terzi** trasmessi al processore esterno
(Azure AI Foundry). MVP **deterministico** (regex) sugli identificatori
strutturati ad alto rischio: Codice Fiscale, P.IVA, email, IBAN, telefoni.
Ogni occorrenza è sostituita da un placeholder tipizzato (`[CF]`, `[EMAIL]`…) e
i conteggi per categoria vengono riportati per l'**audit** (senza esporre i valori).

NON maschera i **nomi propri** di terzi: richiede il riconoscimento entità (NER)
— vedi B7/B1.1 nel backlog.

I pattern sono volutamente **conservativi**: non devono mascherare anni, importi,
date o numeri di procedimento, che servono alla classificazione FATF a valle.
"""
from __future__ import annotations

import re

# Codice Fiscale persona fisica: 6 lettere, 2 cifre, mese∈[A-EHLMPRST], 2 cifre,
# lettera catastale, 3 cifre, char di controllo. Molto specifico → nessun falso positivo.
_CF = re.compile(r"\b[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]\b", re.IGNORECASE)

# IBAN: 2 lettere paese + 2 check + 10-30 alfanumerici. Va PRIMA di P.IVA/telefono
# (contiene lunghe sequenze di cifre che altrimenti verrebbero spezzate).
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", re.IGNORECASE)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# P.IVA: 11 cifre consecutive. Rischio basso: 11 cifre unite raramente sono un importo
# (che di norma ha separatori di migliaia).
_PIVA = re.compile(r"(?<!\d)\d{11}(?!\d)")

# Telefono IT (conservativo). Due forme:
#  - con prefisso +39 (separatori opzionali);
#  - senza prefisso: si RICHIEDE un separatore tra prefisso urbano/mobile e corpo,
#    così non si agganciano importi/anni scritti senza separatori.
# Mobile 3xx, fisso 0x/0xx; corpo 6-8 cifre; niente cifre a ridosso (boundary).
_PHONE = re.compile(
    r"(?<!\d)(?:"
    r"\+39[\s.]?(?:3\d{2}|0\d{1,3})[\s.\-]?\d{6,8}"
    r"|(?:3\d{2}|0\d{1,3})[\s.\-]\d{6,8}"
    r")(?!\d)"
)

# Ordine di applicazione: email e IBAN per primi (sequenze lunghe), poi CF, poi i
# numerici nudi (P.IVA, telefono).
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email", _EMAIL),
    ("iban", _IBAN),
    ("cf", _CF),
    ("piva", _PIVA),
    ("tel", _PHONE),
]

_PLACEHOLDER = {
    "email": "[EMAIL]", "iban": "[IBAN]", "cf": "[CF]",
    "piva": "[P.IVA]", "tel": "[TELEFONO]",
}


def redact(text: str) -> tuple[str, dict]:
    """Redige le PII strutturate dal testo.

    Ritorna `(testo_redatto, report)` con
    `report = {"total": int, "by_category": {categoria: conteggio}}`.
    Il report contiene solo conteggi, mai i valori originali (audit-safe).
    """
    counts: dict[str, int] = {}
    out = text or ""
    for cat, rx in _PATTERNS:
        def _sub(_m: re.Match, _cat: str = cat) -> str:
            counts[_cat] = counts.get(_cat, 0) + 1
            return _PLACEHOLDER[_cat]
        out = rx.sub(_sub, out)
    return out, {"total": sum(counts.values()), "by_category": counts}
