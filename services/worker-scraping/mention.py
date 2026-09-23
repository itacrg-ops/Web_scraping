"""Verifica di menzione del soggetto nell'evidenza (anti falsa attribuzione).

Il soggetto è "citato" solo se compare come **parole intere**, mai come sottostringa:
- CF/P.IVA (identificatore forte);
- persona fisica: nome e cognome **adiacenti**, in qualunque ordine ("Mario Rossi",
  "Rossi Mario"). "Rossi" non vale dentro "Rossini", "Anna" non vale dentro
  "Giovanna", e un "Mario" e un "Rossi" sparsi nell'articolo (due persone diverse)
  non bastano;
- persona giuridica: la denominazione senza forma giuridica (S.r.l., S.p.A., …) come
  sequenza di parole, oppure il nome distintivo (senza parole generiche) se di 2+
  parole; se il nome distintivo è una parola sola (es. "Acme", "Tron") vale solo se
  nel testo compare con l'iniziale maiuscola (nome proprio, non "l'acme della crisi").
  Un'occorrenza seguita da una parola generica che nel nostro nome non c'è (es.
  "ACME Costruzioni **Generali**" per "ACME Costruzioni S.r.l.") è un'ALTRA società.

Complemento dell'anti-omonimia: qui è usata in modo **non bloccante** (warning).
"""
from __future__ import annotations

import difflib
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

# Forme giuridiche (già normalizzate: "S.r.l." → "S R L"), rimosse in coda al nome.
_LEGAL_FORMS = [f.split() for f in sorted((
    "S R L S", "SRLS", "S R L", "SRL", "S P A", "SPA", "S N C", "SNC", "S A S", "SAS",
    "S S", "SS", "S C A R L", "SCARL", "S C P A", "SCPA", "A R L", "ARL", "SOC COOP",
    "SOCIETA COOPERATIVA", "COOP", "ONLUS", "UNIPERSONALE", "IN LIQUIDAZIONE",
), key=lambda f: -len(f.split()))]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> list[str]:
    """Parole normalizzate (maiuscole, senza accenti né punteggiatura)."""
    return _norm(s).split()


def occurrences(hay: list[str], needle: list[str]) -> list[int]:
    """Indici di inizio di `needle` come sequenza CONTIGUA di parole intere in `hay`."""
    n = len(needle)
    if not n:
        return []
    first = needle[0]
    return [i for i, t in enumerate(hay[: len(hay) - n + 1]) if t == first and hay[i:i + n] == needle]


def contains(hay: list[str], needle: list[str]) -> bool:
    return bool(occurrences(hay, needle))


def strip_legal_form(toks: list[str]) -> list[str]:
    """Toglie le forme giuridiche in coda ("ACME COSTRUZIONI S R L" → "ACME COSTRUZIONI")."""
    out = list(toks)
    changed = True
    while changed:
        changed = False
        for lf in _LEGAL_FORMS:
            if len(out) > len(lf) and out[-len(lf):] == lf:
                out, changed = out[:-len(lf)], True
                break
    return out


def _capitalized_in(text: str, token: str) -> bool:
    """`token` (normalizzato) compare nel testo ORIGINALE con l'iniziale maiuscola."""
    return any(w[0].isupper() and _norm(w) == token for w in re.findall(r"\w+", text or ""))


def _person_names(subject: dict) -> tuple[list[str], list[str]]:
    nome, cognome = tokens(subject.get("nome", "")), tokens(subject.get("cognome", ""))
    if not (nome or cognome):  # in mancanza: denominazione "Cognome Nome"
        toks = tokens(subject.get("denominazione", ""))
        cognome, nome = toks[:1], toks[1:]
    return nome, cognome


def person_in(name_tokens: list[str], subject: dict) -> bool:
    """Il nome (es. un'entità PERSONA della NER) contiene nome e cognome del soggetto
    ADIACENTI, in qualunque ordine, come parole intere."""
    nome, cognome = _person_names(subject)
    if not (nome and cognome):
        return False
    return contains(name_tokens, nome + cognome) or contains(name_tokens, cognome + nome)


def org_matches(a: str, b: str) -> bool:
    """Due denominazioni si riferiscono alla stessa organizzazione: la più corta (senza
    forma giuridica) è una sequenza di parole intere della più lunga e ha almeno una
    parola non generica."""
    ta, tb = strip_legal_form(tokens(a)), strip_legal_form(tokens(b))
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return bool(short) and any(t not in GENERIC for t in short) and contains(long_, short)


def _check_person(subject: dict, ttoks: list[str], matched: list[str]) -> list[str]:
    nome, cognome = _person_names(subject)
    if nome and cognome and person_in(ttoks, subject):
        matched.append("nome_cognome")
    return [t for t in nome + cognome if len(t) >= 3]


def _entity_occurs(ttoks: list[str], phrase: list[str], full: list[str]) -> bool:
    """`phrase` compare come parole intere e, saltate le parole del nostro stesso nome,
    NON prosegue con una parola generica che nel nostro nome non c'è (altrimenti è
    un'altra società: "ACME [Costruzioni] Generali" non è "ACME Costruzioni")."""
    own, other_generic = set(full), GENERIC - set(full)
    for i in occurrences(ttoks, phrase):
        j = i + len(phrase)
        while j < len(ttoks) and ttoks[j] in own:
            j += 1
        if j >= len(ttoks) or ttoks[j] not in other_generic:
            return True
    return False


def _check_entity(subject: dict, text: str, ttoks: list[str], matched: list[str]) -> list[str]:
    full = strip_legal_form(tokens(subject.get("denominazione", "")))
    core = [t for t in full if t not in GENERIC]
    if full and _entity_occurs(ttoks, full, full):
        matched.append("denominazione")
    elif len(core) >= 2 and _entity_occurs(ttoks, core, full):
        matched.append("denominazione")
    elif (len(core) == 1 and len(core[0]) >= 3 and _entity_occurs(ttoks, core, full)
          and _capitalized_in(text, core[0])):
        matched.append("denominazione_breve")
    return core


def _context_matches(subject: dict, ttoks: list[str]) -> list[str]:
    """Corroborazione anti-omonimia: quali qualificatori (azienda/località/ruolo)
    compaiono nel testo come parole intere ("Roma" non vale dentro "Romania").
    Il ruolo è un segnale debole (soft)."""
    return [key for key in ("azienda", "localita", "ruolo")
            if (v := tokens(subject.get(key, ""))) and contains(ttoks, v)]


# Una parola "vicina" a una del nome del soggetto (refuso: Stropp / Stroppa / Stropa).
# 0.85 esclude le coppie di nomi corti e comuni (Rossi/Rosso, Mario/Maria), quasi
# sempre persone diverse.
_NEAR = 0.85


def _near(a: str, b: str) -> bool:
    return a != b and min(len(a), len(b)) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= _NEAR


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text or "")


def name_variants(subject: dict, text: str) -> list[str]:
    """Varianti VICINE al nome del soggetto citate nel testo, quando il nome esatto non
    c'è: di solito un refuso nel nome inserito («Stropp Andrea» → gli articoli dicono
    «Andrea Stroppa»). Persona: il nome di battesimo esatto accanto a una parola simile
    al cognome (o viceversa), con le iniziali maiuscole. Impresa: il nome distintivo con
    una parola simile. Restituisce le varianti come scritte nel testo."""
    words = _words(text)
    norm = [_norm(w) for w in words]
    found: list[str] = []

    def add(i: int, j: int) -> None:
        v = " ".join(words[i:j + 1])
        if v not in found and all(w[:1].isupper() for w in words[i:j + 1]):
            found.append(v)

    if (subject.get("tipo_soggetto") or "persona_giuridica") == "persona_fisica":
        nome, cognome = _person_names(subject)
        if len(nome) != 1 or len(cognome) != 1:
            return []
        first, last = nome[0], cognome[0]
        for i in range(len(norm) - 1):
            a, b = norm[i], norm[i + 1]
            if (a == first and _near(b, last)) or (b == first and _near(a, last)) \
                    or (a == last and _near(b, first)) or (b == last and _near(a, first)):
                add(i, i + 1)
    else:
        core = [t for t in strip_legal_form(tokens(subject.get("denominazione", ""))) if t not in GENERIC]
        n = len(core)
        for i in range(len(norm) - n + 1):
            window = norm[i:i + n]
            if window != core and all(w == c or _near(w, c) for w, c in zip(window, core)):
                add(i, i + n - 1)
    return found[:5]


def check(subject: dict, text: str) -> dict:
    ttoks = tokens(text)
    matched: list[str] = []

    cf = re.sub(r"[^A-Z0-9]", "", (subject.get("cf_piva") or "").upper())
    if cf and cf in "".join(ttoks):
        matched.append("cf_piva")

    if (subject.get("tipo_soggetto") or "persona_giuridica") == "persona_fisica":
        distinctive = _check_person(subject, ttoks, matched)
    else:
        distinctive = _check_entity(subject, text, ttoks, matched)

    return {
        "mentioned": bool(matched),
        "matched": sorted(set(matched)),
        "distinctive": distinctive,
        "context": _context_matches(subject, ttoks),
        # solo se il nome esatto manca: altrimenti una variante è rumore
        "variants": [] if matched else name_variants(subject, text),
    }
