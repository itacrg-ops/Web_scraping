"""Costruzione delle query di ricerca adverse-media (§ Search & Scraping).

Due modalità:
  - `broad`: solo il nome del soggetto (varianti);
  - `targeted`: nome AND termini avversi (allineati alla tassonomia FATF).

Le varianti del nome coprono l'ordine "Nome Cognome" e "Cognome Nome" per le
persone fisiche; per le persone giuridiche si usa la denominazione. La sintassi
booleana (frasi tra virgolette, OR, parentesi) è compatibile con GDELT DOC 2.0.

Impresa con nome di UNA parola ("Vita S.r.l."): la parola da sola è spesso una parola
comune e i motori restituirebbero articoli su tutt'altro ("la vita…"). Si cerca allora
la ragione sociale con la forma giuridica ("Vita Srl", "Vita S.r.l."), come farebbe
una persona; la parola da sola solo se lunga (probabile nome di fantasia: "Italware").
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


# Forma giuridica nella denominazione → come la scrivono gli articoli (senza e con punti).
_LEGAL_WRITINGS: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"\bs\.?\s*r\.?\s*l\.?\s*s\.?$", re.I), ["Srls", "S.r.l.s."]),
    (re.compile(r"\bs\.?\s*r\.?\s*l\.?$", re.I), ["Srl", "S.r.l."]),
    (re.compile(r"\bs\.?\s*p\.?\s*a\.?$", re.I), ["SpA", "S.p.A."]),
    (re.compile(r"\bs\.?\s*n\.?\s*c\.?$", re.I), ["Snc", "S.n.c."]),
    (re.compile(r"\bs\.?\s*a\.?\s*s\.?$", re.I), ["Sas", "S.a.s."]),
]
# Forma giuridica non indicata: le più comuni.
_DEFAULT_WRITINGS = ["Srl", "SpA"]
# Nome di una parola sola abbastanza lungo da essere quasi certamente un nome di
# fantasia (Italware), cercabile anche da solo.
_DISTINCTIVE_LEN = 8


def _legal_writings(denominazione: str) -> list[str]:
    d = denominazione.strip()
    for rx, writings in _LEGAL_WRITINGS:
        if rx.search(d):
            return writings
    return _DEFAULT_WRITINGS


def single_word_entity(subject: dict) -> str | None:
    """La parola del nome d'impresa se è UNA sola ("Vita S.r.l." → "Vita"), altrimenti None."""
    if _is_person(subject):
        return None
    d = (subject.get("denominazione") or "").strip()
    cleaned = _clean_entity_name(d) if d else ""
    return cleaned if cleaned and len(cleaned.split()) == 1 else None


def _entity_names(subject: dict) -> list[str]:
    d = (subject.get("denominazione") or "").strip()
    if not d:
        return []
    word = single_word_entity(subject)
    if word:
        # Ragione sociale completa, nelle scritture usate dagli articoli.
        names = [f"{word} {w}" for w in _legal_writings(d)]
        return names + ([word] if len(word) >= _DISTINCTIVE_LEN else [])
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


def has_qualifiers(subject: dict) -> bool:
    """Persona fisica con azienda/località: i qualificatori la distinguono dagli omonimi."""
    return bool(_qualifiers(subject))


_ADVERSE_RX = re.compile(r"\b(?:" + "|".join(map(re.escape, ADVERSE_TERMS)) + r")\b", re.IGNORECASE)


def has_adverse_terms(query_str: str) -> bool:
    """La query contiene i termini avversi (gradino "targeted" della scala)."""
    return bool(_ADVERSE_RX.search(query_str or ""))


def build_query(subject: dict, mode: str = "targeted") -> str:
    """Query singola: la PIÙ PRECISA per la modalità. Per la scala completa di
    fallback (usata dai provider) vedi `build_query_variants`."""
    variants = build_query_variants(subject, mode)
    return variants[0] if variants else ""


def build_query_variants(subject: dict, mode: str = "targeted",
                         syntax: str = "boolean") -> list[str]:
    """Query in ordine dalla PIÙ PRECISA alla PIÙ LARGA (scala). GDELT le prova in
    sequenza e si ferma alla prima con articoli; Brave e SearXNG sommano i risultati
    delle varie query (prima quelli delle più precise) finché non bastano — tranne per
    la persona con azienda/località, dove ci si allarga solo se non si trova nulla.

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
    if single_word_entity(subject):
        # Prima la ragione sociale (con forma giuridica), poi — se il nome è distintivo —
        # la parola da sola. Mai la parola comune da sola.
        full = [n for n in names if len(n.split()) > 1]
        clauses = [_name_clause(full)] + ([f'"{names[-1]}"'] if len(names) > len(full) else [])
        if mode == "broad":
            return clauses
        return [x for c in clauses for x in (f"{c} {_adverse_clause()}", c)]
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
    # entità: una query per scrittura del nome (ragione sociale completa per prima)
    if mode == "broad":
        return q_names
    adverse = " ".join(ADVERSE_TERMS)
    return [f"{qn} {adverse}" for qn in q_names] + q_names


def _squash(text: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def cites_full_name(result: dict, subject: dict) -> bool:
    """Titolo o estratto citano la ragione sociale completa ("Vita Srl"/"Vita S.r.l."):
    per un'impresa con nome di una parola è il segnale che parla proprio di lei."""
    hay = f" {_squash(result.get('title'))} {_squash(result.get('snippet'))} "
    return any(f" {_squash(n)} " in hay for n in name_variants(subject) if len(n.split()) > 1)
