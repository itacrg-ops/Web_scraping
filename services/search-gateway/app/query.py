"""Costruzione delle query di ricerca adverse-media (§ Search & Scraping).

Due modalità:
  - `broad`: solo il nome del soggetto (varianti);
  - `targeted`: nome AND termini avversi (allineati alla tassonomia FATF).

Le varianti del nome coprono l'ordine "Nome Cognome" e "Cognome Nome" per le
persone fisiche; per le persone giuridiche si usa la denominazione. La sintassi
booleana (frasi tra virgolette, OR, parentesi) è compatibile con GDELT DOC 2.0.
"""
from __future__ import annotations

import re

PERSONA_FISICA = "persona_fisica"

# Termini avversi (IT) allineati alla tassonomia FATF / reati-spia PA-appalti.
# Set compatto (GDELT limita la lunghezza/numero di OR): i termini più salienti;
# il resto emerge comunque dalla classificazione FATF a valle.
ADVERSE_TERMS: list[str] = [
    "indagato", "arrestato", "inchiesta", "corruzione",
    "riciclaggio", "frode", "sequestro", "condannato",
]

# Forme societarie da rimuovere dal nome per la ricerca ("Tron Group Holding
# S.r.l." → "Tron Group Holding"): negli articoli il nome compare senza suffisso.
_LEGAL_RE = re.compile(
    r"\b(srls?|spa|snc|sas|ss|soc(?:ieta)?\s*coop(?:erativa)?|coop|scarl|scpa|onlus|aps|ets)\b",
    re.IGNORECASE,
)


def _clean_entity_name(name: str) -> str:
    s = re.sub(r"&\s*C\.?", " ", name, flags=re.IGNORECASE)
    s = s.replace(".", "")          # "S.r.l." → "Srl" (poi rimosso)
    s = _LEGAL_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or name.strip()


def _person_names(subject: dict) -> list[str]:
    nome = (subject.get("nome") or "").strip()
    cognome = (subject.get("cognome") or "").strip()
    if not (nome or cognome):
        toks = (subject.get("denominazione") or "").split()
        if len(toks) >= 2:
            cognome, nome = toks[0], " ".join(toks[1:])
        elif toks:
            cognome = toks[0]
    if nome and cognome:
        variants = [f"{nome} {cognome}", f"{cognome} {nome}"]
    elif cognome:
        variants = [cognome]
    elif nome:
        variants = [nome]
    else:
        variants = []
    return list(dict.fromkeys(variants))  # dedup preservando l'ordine


def _entity_names(subject: dict) -> list[str]:
    d = (subject.get("denominazione") or "").strip()
    if not d:
        return []
    cleaned = _clean_entity_name(d)
    # Usa il nome senza forma societaria (match più probabile negli articoli).
    return [cleaned] if cleaned else [d]


def _is_person(subject: dict) -> bool:
    return (subject.get("tipo_soggetto") or "persona_giuridica") == PERSONA_FISICA


def name_variants(subject: dict) -> list[str]:
    return _person_names(subject) if _is_person(subject) else _entity_names(subject)


def _qualifiers(subject: dict) -> list[str]:
    """Qualificatori forti per la persona fisica: azienda e località, come frasi
    quotate in AND. Riducono drasticamente l'omonimia. Il RUOLO NON entra qui:
    da solo raramente compare negli articoli e in AND taglierebbe il recall
    (è usato a valle come corroborazione)."""
    if not _is_person(subject):
        return []
    out = []
    for key in ("azienda", "localita"):
        v = (subject.get(key) or "").strip()
        if v:
            out.append(f'"{v}"')
    return out


def build_query(subject: dict, mode: str = "targeted") -> str:
    names = name_variants(subject)
    if not names:
        return ""
    if len(names) > 1:
        name_clause = "(" + " OR ".join(f'"{n}"' for n in names) + ")"
    else:
        name_clause = f'"{names[0]}"'

    quals = _qualifiers(subject)
    base = " ".join([name_clause, *quals])

    if mode == "broad":
        return base
    # Se ci sono qualificatori forti (azienda/località) il soggetto è già molto
    # specifico: NON aggiungo l'AND sui termini avversi, per preservare il recall
    # sulla persona giusta (l'adverse lo decide la classificazione FATF a valle).
    if quals:
        return base
    adverse_clause = "(" + " OR ".join(ADVERSE_TERMS) + ")"
    return f"{base} {adverse_clause}"
