"""Estrazione di dati anagrafici dagli articoli per mitigare l'omonimia (B7).

Regex leggere (IT) per età, anno/data di nascita e luogo di nascita citati nel
testo; confronto con i dati del soggetto. Se l'articolo riporta un'età o un luogo
di nascita DISCORDANTI da quelli del soggetto, è un forte indizio di **omonimo**;
se COINCIDONO, corroborano l'identità.

Deterministico e senza dipendenze: complementare al NER (B7 parte 2), che darà
copertura più ampia (persone/organizzazioni).
"""
from __future__ import annotations

import re
from datetime import datetime

import mention

# "45 anni", "di 45 anni"
_AGE = re.compile(r"\b(?:di\s+)?(\d{1,3})\s+anni\b", re.IGNORECASE)
# "45enne", "45-enne"
_AGE_ENNE = re.compile(r"\b(\d{1,3})\s*-?enne\b", re.IGNORECASE)
# "classe 1980", "nato nel 1980"
_BIRTH_YEAR = re.compile(r"\b(?:classe|nat[oa]\s+(?:nel\s+)?)\s*(\d{4})\b", re.IGNORECASE)
# "nato il 20/05/1980", "nata il 20-05-1980"
_BIRTH_DATE = re.compile(r"\bnat[oa]\s+il\s+\d{1,2}[/\-.]\d{1,2}[/\-.](\d{4})\b", re.IGNORECASE)
# "nato a Milano", "nata a Reggio Emilia" (1-2 parole con iniziale maiuscola)
_BIRTHPLACE = re.compile(r"\bnat[oa]\s+a\s+([A-ZÀ-Ù][\wàèéìòù'\-]+(?:\s+[A-ZÀ-Ù][\wàèéìòù'\-]+)?)")


_PLACE_STOP = {"DI", "DEL", "DELLA", "DELLO", "DEI", "DEGLI", "DELLE", "NELL", "NEL", "NELLA",
               "IN", "SU", "SUL", "SULLA", "A", "AL", "ALLA", "E", "D", "L"}


def _place(s: str) -> list[str]:
    return [t for t in mention.tokens(s) if t not in _PLACE_STOP]


def extract(text: str) -> dict:
    t = text or ""
    ages = {int(m) for m in _AGE.findall(t) + _AGE_ENNE.findall(t) if 0 < int(m) <= 120}
    years = {int(m) for m in _BIRTH_YEAR.findall(t) + _BIRTH_DATE.findall(t) if 1900 <= int(m) <= datetime.now().year}
    places = {p.strip() for p in _BIRTHPLACE.findall(t) if p.strip()}
    return {"ages": sorted(ages), "years": sorted(years), "birthplaces": sorted(places)}


def corroborate(subject: dict, text: str) -> dict:
    """Confronta i dati anagrafici del soggetto con quelli citati nell'articolo.
    Ritorna {status, findings, extracted} con status ∈
    {confermato, discordante, assente, n/a}."""
    if (subject.get("tipo_soggetto") or "persona_giuridica") != "persona_fisica":
        return {"status": "n/a", "findings": [], "extracted": {}}
    ex = extract(text)
    findings: list[str] = []
    confirm = conflict = False

    dob = (subject.get("data_nascita") or "").strip()
    birth_year = int(dob[:4]) if dob[:4].isdigit() else None
    if birth_year:
        expected_age = datetime.now().year - birth_year
        for a in ex["ages"]:
            if abs(a - expected_age) <= 1:
                confirm = True
                findings.append(f"età {a} coerente con la data di nascita")
            elif abs(a - expected_age) >= 3:
                conflict = True
                findings.append(f"età {a} discordante (attesa ~{expected_age})")
        for y in ex["years"]:
            if y == birth_year:
                confirm = True
                findings.append(f"anno di nascita {y} confermato")
            elif abs(y - birth_year) >= 2:
                conflict = True
                findings.append(f"anno di nascita {y} discordante (atteso {birth_year})")

    # Luogo: confronto a PAROLE INTERE ("Roma" non vale dentro "Romano"), ignorando le
    # preposizioni ("Reggio nell'Emilia" = "Reggio Emilia") e accettando il contenimento
    # nei due sensi (la regex cattura al più 2 parole: "San Giovanni [Rotondo]"). Un
    # luogo diverso citato con "nato a …" è una discordanza (possibile omonimo).
    luogo = _place(subject.get("luogo_nascita") or "")
    if luogo:
        for bp in ex["birthplaces"]:
            b = _place(bp)
            if not b:
                continue
            if mention.contains(b, luogo) or mention.contains(luogo, b):
                confirm = True
                findings.append(f"luogo di nascita «{bp}» confermato")
            else:
                conflict = True
                findings.append(f"luogo di nascita «{bp}» discordante (atteso {subject.get('luogo_nascita')})")

    status = "discordante" if conflict else ("confermato" if confirm else "assente")
    return {"status": status, "findings": findings, "extracted": ex}
