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


def _name_clause(names: list[str]) -> str:
    if len(names) > 1:
        return "(" + " OR ".join(f'"{n}"' for n in names) + ")"
    return f'"{names[0]}"'


def _adverse_clause() -> str:
    return "(" + " OR ".join(ADVERSE_TERMS) + ")"


def build_query(subject: dict, mode: str = "targeted") -> str:
    """Query singola: la PIÙ PRECISA per la modalità. Per la scala completa di
    fallback (usata dai provider) vedi `build_query_variants`."""
    variants = build_query_variants(subject, mode)
    return variants[0] if variants else ""


def build_query_variants(subject: dict, mode: str = "targeted",
                         syntax: str = "boolean") -> list[str]:
    """Query in ordine dalla PIÙ PRECISA alla PIÙ LARGA (fallback ladder). I
    provider le provano in sequenza e si fermano alla prima con articoli.

    `syntax` adatta la sintassi al provider:
      - "boolean" (GDELT): supporta i gruppi `("A" OR "B")` e l'OR — un'unica
        query copre entrambi gli ordini del nome e i termini avversi in OR;
      - "plain" (Brave/Google): NON supporta parentesi/OR in modo affidabile e
        tratta OGNI frase tra virgolette come AND obbligatorio. Quindi un solo
        ordine del nome per query (gli altri ordini diventano varianti
        successive) e termini avversi NON quotati (segnali soft di ranking).

      persona + qualificatori : nome+azienda+località → nome+azienda → nome
      persona senza qualif. / entità (targeted): nome+avversi → nome
      qualsiasi soggetto (broad): solo nome

    Quando la query si allarga al solo nome, la garanzia sull'identità resta
    l'anti-omonimia a valle (verifica di azienda/località nel testo degli articoli).
    """
    names = name_variants(subject)
    if not names:
        return []
    variants = (_plain_variants(subject, names, mode) if syntax == "plain"
                else _boolean_variants(subject, names, mode))
    seen: set[str] = set()
    return [v for v in variants if not (v in seen or seen.add(v))]


def _boolean_variants(subject: dict, names: list[str], mode: str) -> list[str]:
    """GDELT: `("A" OR "B")` + termini avversi in OR (una query per entrambi gli
    ordini del nome). Togliendo un qualificatore alla volta partendo dall'ultimo
    (località): l'azienda, più distintiva, resta fino all'ultimo prima del nome."""
    nc = _name_clause(names)
    if mode == "broad":
        return [nc]
    if _is_person(subject):
        quals = _qualifiers(subject)
        if quals:
            out = [" ".join([nc, *quals[:i]]) for i in range(len(quals), 0, -1)]
            return out + [nc]
        return [f"{nc} {_adverse_clause()}", nc]
    return [f"{nc} {_adverse_clause()}", nc]


def _plain_variants(subject: dict, names: list[str], mode: str) -> list[str]:
    """Brave/Google: niente parentesi/OR; ogni frase tra virgolette è AND forte.
    Un solo ordine del nome per query (gli altri come varianti successive) e
    termini avversi NON quotati (soft, non filtranti)."""
    q_names = [f'"{nm}"' for nm in names]
    if _is_person(subject):
        if mode == "broad":
            return q_names
        quals = _qualifiers(subject)
        if quals:
            out: list[str] = []
            for i in range(len(quals), 0, -1):
                out += [" ".join([qn, *quals[:i]]) for qn in q_names]
            return out + q_names
        adverse = " ".join(ADVERSE_TERMS)
        return [f"{qn} {adverse}" for qn in q_names] + q_names
    # entità: la denominazione ripulita è già l'unico nome
    qn = q_names[0]
    if mode == "broad":
        return [qn]
    return [f"{qn} " + " ".join(ADVERSE_TERMS), qn]
