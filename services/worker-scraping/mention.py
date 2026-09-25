"""Verifica di menzione del soggetto nell'evidenza (anti falsa attribuzione).

Il soggetto è "citato" solo se compare come **parole intere**, mai come sottostringa:
- CF/P.IVA (identificatore forte);
- persona fisica: nome e cognome **adiacenti**, in qualunque ordine ("Mario Rossi",
  "Rossi Mario"). "Rossi" non vale dentro "Rossini", "Anna" non vale dentro
  "Giovanna", e un "Mario" e un "Rossi" sparsi nell'articolo (due persone diverse)
  non bastano;
- persona giuridica: la denominazione senza forma giuridica (S.r.l., S.p.A., …) come
  sequenza di parole, oppure il nome distintivo (senza parole generiche) se di 2+
  parole, scritti come nome proprio (iniziale maiuscola: "Nuova Vita", non "una nuova
  vita"). Se il nome è di UNA parola ("Vita S.r.l.", "Tron") vale se è usato come nome
  d'impresa — seguito dalla forma giuridica ("Vita Srl") o preceduto da "società",
  "ditta", "gruppo"… — oppure se compare come nome proprio a metà frase e mai in
  minuscolo nel testo ("La Tron ha vinto", non "l'acme della crisi" né "la vita…").
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


# Parole che, subito prima del nome, dicono che si parla di un'impresa ("società Vita").
_COMPANY_WORDS = {"SOCIETA", "DITTA", "AZIENDA", "IMPRESA", "GRUPPO", "CONSORZIO", "COOPERATIVA"}


def _word_spans(text: str) -> list[tuple[str, str, bool]]:
    """Parole del testo: (originale, normalizzata, a inizio frase)."""
    out = []
    for m in re.finditer(r"\w+", text or ""):
        n = _norm(m.group())
        if n:
            before = text[:m.start()].rstrip(" \t\"'«“‘(")
            out.append((m.group(), n, not before or before[-1] in ".!?:;\n"))
    return out


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


def _entity_hits(norm: list[str], phrase: list[str], full: list[str]) -> list[int]:
    """Occorrenze di `phrase` come parole intere che, saltate le parole del nostro stesso
    nome, NON proseguono con una parola generica che nel nostro nome non c'è (altrimenti
    è un'altra società: "ACME [Costruzioni] Generali" non è "ACME Costruzioni")."""
    own, other_generic = set(full), GENERIC - set(full)
    hits = []
    for i in occurrences(norm, phrase):
        j = i + len(phrase)
        while j < len(norm) and norm[j] in own:
            j += 1
        legal_form = any(norm[j:j + len(lf)] == lf for lf in _LEGAL_FORMS)   # "… Srl": è la nostra
        if j >= len(norm) or legal_form or norm[j] not in other_generic:
            hits.append(i)
    return hits


def _as_company(norm: list[str], i: int, n: int) -> bool:
    """L'occorrenza norm[i:i+n] è usata come nome d'impresa: seguita dalla forma
    giuridica ("Vita Srl", "Vita S.r.l.") o preceduta da "società", "ditta", "gruppo"…"""
    after = norm[i + n:i + n + 5]
    return any(after[:len(lf)] == lf for lf in _LEGAL_FORMS) or (i > 0 and norm[i - 1] in _COMPANY_WORDS)


def _check_entity(subject: dict, text: str, ttoks: list[str], matched: list[str]) -> list[str]:
    full = strip_legal_form(tokens(subject.get("denominazione", "")))
    core = [t for t in full if t not in GENERIC]
    words = _word_spans(text)
    norm = [n for _, n, _ in words]
    proper = lambda i: words[i][0][:1].isupper()   # noqa: E731 — iniziale maiuscola

    # Nome di più parole: come sequenza, scritto da nome proprio (o come impresa).
    for phrase in (full, core):
        if len(phrase) >= 2 and any(proper(i) or _as_company(norm, i, len(phrase))
                                    for i in _entity_hits(norm, phrase, full)):
            matched.append("denominazione")
            return core
    # Nome di una parola: usato come impresa, oppure nome proprio a metà frase e mai
    # in minuscolo nel testo (altrimenti è la parola comune: "la vita", "l'acme").
    single = full if len(full) == 1 else core if len(core) == 1 else []
    if single and len(single[0]) >= 3:
        hits = _entity_hits(norm, single, full)
        if any(_as_company(norm, i, 1) for i in hits):
            matched.append("denominazione")
        elif (any(proper(i) and not words[i][2] for i in hits)
              and not any(not proper(i) for i in hits)):
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
