"""Classificatore FATF — **euristica a keyword** sul testo realmente estratto.

Placeholder trasparente in attesa del classificatore dual-LLM (§3): rileva
segnali adverse-media e li mappa alle categorie FATF, individuando anche il
ruolo processuale. Nessuna fabbricazione: opera sul testo effettivo. TODO:
sostituire/integrare con il parsing strutturato dell'output del llm-gateway.
"""
from __future__ import annotations

import re

# term (regex, case-insensitive) → categoria FATF
_RULES: list[tuple[str, str]] = [
    (r"corruzion|concussion|tangent|turbativ|mazzett", "Corruption & Bribery"),
    (r"frode|frodi|truffa|bancarott|fals|evasione fiscale", "Fraud & Financial Crime"),
    (r"ricicl|autoricicl|antiricicl", "Money Laundering"),
    (r"mafi|'?ndranghet|camorr|associazione (a|per) delinquere|interdittiv[ao] antimafia", "Organized Crime"),
    (r"terroris|finanziamento del terrorismo", "Terrorist Financing"),
]

_ROLE_RULES: list[tuple[str, str]] = [
    (r"condann", "condanna"),
    (r"rinvi[ao] a giudizio|imputat", "rinvio_a_giudizio"),
    (r"archivi|proscioglimento|assolt", "archiviazione"),
    (r"indag|arrest|sequestr|misura cautelar|custodia cautelar|perquisizion", "indagine_preliminare"),
]


def classify_text(text: str) -> dict:
    t = (text or "").lower()
    categories: list[str] = []
    for pattern, cat in _RULES:
        if re.search(pattern, t) and cat not in categories:
            categories.append(cat)

    ruolo = None
    for pattern, role in _ROLE_RULES:
        if re.search(pattern, t):
            ruolo = role
            break

    return {
        "fatf_categories": categories,
        "ruolo_processuale": ruolo,
        "method": "euristica_keyword",
        "confidence": 0.6 if categories else 0.0,
    }
