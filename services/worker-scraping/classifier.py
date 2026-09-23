"""Classificatore FATF — **euristica a keyword** sul testo realmente estratto.

Ripiego usato SOLO se il classificatore dual-LLM (llm-gateway) non è disponibile:
il workflow marca allora l'esito come INCOMPLETO (le categorie a keyword non sono
affidabili). Nessuna fabbricazione: opera sul testo effettivo.

Le regole privilegiano la **precisione**: niente radici generiche che nel dominio
FSC/MASE producono falsi positivi — "riciclo"/"riciclaggio dei rifiuti" (impianti
ambientali), "anticorruzione" (ANAC), "antimafia" (white list, certificazioni),
"falso" (notizie false), "indagine geologica/di mercato", "arresto cardiaco".
"""
from __future__ import annotations

import re

_ORDER = ["Corruption & Bribery", "Fraud & Financial Crime", "Money Laundering",
          "Organized Crime", "Terrorist Financing"]

# "anti…": "anticorruzione", "antimafia" sono presidi/adempimenti, non notizie avverse
# (l'interdittiva antimafia invece sì: regola esplicita).
_NOT_ANTI = r"(?<!anti)(?<!anti-)(?<!anti )"

# term (regex sul testo minuscolo) → categoria FATF
_RULES: list[tuple[str, str]] = [
    (_NOT_ANTI + r"corruzion|concussion|tangent|turbativ|mazzett", "Corruption & Bribery"),
    (r"frode|frodi|truffa|bancarott|evasione fiscale|falso in bilancio|false comunicazioni sociali"
     r"|falso ideologico|falso materiale|falsificazion|fatture false|falsa fatturazion",
     "Fraud & Financial Crime"),
    (_NOT_ANTI + r"mafi|'?ndranghet|camorr|associazione (a|per) delinquere"
     r"|interdittiv[ao] antimafia|antimafia interdittiv", "Organized Crime"),
    (r"terroris|finanziamento del terrorismo", "Terrorist Financing"),
]

# Riciclaggio. "autoriciclaggio" e "riciclava/riciclato denaro…" sono univoci;
# "riciclaggio" in italiano indica ANCHE il riciclo dei materiali: conta come reato
# salvo che il contesto vicino sia chiaramente quello dei rifiuti SENZA riferimenti a
# denaro/reati. "riciclo" e "antiriciclaggio" (normativa, presidi) non contano mai.
_ML_TERM = re.compile(r"\bautoriciclaggio\b|\briciclaggio\b"
                      r"|\bricicla(?:va|vano|to|ti|re|ndo)\s+(?:il\s+|i\s+)?(?:denaro|soldi|capitali|proventi)")
_RECYCLING_CTX = re.compile(
    r"\brifiuti\b|raccolta differenziata|differenziat|economia circolare|\bplastica\b|\bvetro\b"
    r"|imballagg|pneumatic|compost|\braee\b|materie prime seconde|isola ecologica"
    r"|impianto di (?:riciclaggio|recupero|trattamento)"
    r"|riciclaggio (?:della|delle|dei|degli|del|di) (?:carta|plastic|vetro|material|rifiut|pneumatic"
    r"|batteri|metall|legno|tessil|inert|oli)")
_MONEY_CTX = re.compile(r"denaro|\bsoldi\b|\bcapitali\b|provent|illecit|\breat[oi]\b|indagat|procura della"
                        r"|guardia di finanza|contant|\bbonifici\b|bonifico bancari|648[- ]?(?:bis|ter)")
_ML_WINDOW = 80  # caratteri di contesto per lato


def _money_laundering(t: str) -> bool:
    for m in _ML_TERM.finditer(t):
        if m.group(0) != "riciclaggio":          # autoriciclaggio / "riciclava denaro…"
            return True
        ctx = t[max(0, m.start() - _ML_WINDOW): m.end() + _ML_WINDOW]
        if not _RECYCLING_CTX.search(ctx) or _MONEY_CTX.search(ctx):
            return True
    return False


_ROLE_RULES: list[tuple[str, str]] = [
    (r"condann", "condanna"),
    (r"rinvi[ao] a giudizio|imputat", "rinvio_a_giudizio"),
    (r"richiesta di archiviazion|decreto di archiviazion"
     r"|archiviazione (?:del|della|dell')\s?(?:procediment|inchiest|indagin|posizion|caso)"
     r"|archiviat[oa] (?:il|la|l')\s?(?:procediment|inchiest|indagin|posizion|caso)"
     r"|proscioglimento|prosciolt|\bassolt[oaie]\b", "archiviazione"),
    (r"indagat[oaie]|indagine (?:della procura|penale|giudiziaria)"
     r"|inchiesta (?:della procura|giudiziaria|penale)|\barrestat[oaie]\b|\barresti\b"
     r"|\barresto\b(?! cardiac)|sequestr|misura cautelar|custodia cautelar|perquisizion"
     r"|avviso di garanzia|informazione di garanzia", "indagine_preliminare"),
]


def classify_text(text: str) -> dict:
    t = (text or "").lower()
    found = {cat for pattern, cat in _RULES if re.search(pattern, t)}
    if _money_laundering(t):
        found.add("Money Laundering")
    categories = [c for c in _ORDER if c in found]

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
