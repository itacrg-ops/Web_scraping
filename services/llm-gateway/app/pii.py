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
import unicodedata

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


# --- Redazione dei NOMI di persona (B1.1, con NER) -------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def _name_variants(name: str) -> list[str]:
    """Il nome così com'è e in tutti gli ordini «Nome Cognome» possibili: con "Cognome
    Nome" non si sa dove finisce il cognome ("Messina Denaro Matteo" → "Matteo Messina
    Denaro", "Denaro Matteo Messina")."""
    parts = (name or "").split()
    if not parts:
        return []
    out = {" ".join(parts[k:] + parts[:k]) for k in range(len(parts))}
    return sorted(out, key=len, reverse=True)


_INITIAL = re.compile(r"^[A-Z]\.?$")


def _names_same_person(person: str, subject_tokens: set[str]) -> bool:
    """Il nome trovato dalla NER indica il soggetto? Sì se è **parte** del nome del
    soggetto ("Rossi", "Mario Rossi", "M. Rossi" per "Rossi Mario") o lo **contiene**
    per intero (un secondo nome in più). Condividere UNA sola parola non basta:
    "Mario Verdi" (stesso nome di battesimo) o "Luca Rossi" (stesso cognome) sono
    altre persone, e trattarle come soggetto gli attribuirebbe i fatti altrui."""
    tokens = _norm(person).replace(".", ". ").split()
    words = [t for t in tokens if not _INITIAL.match(t)]
    if not words or not subject_tokens:
        return False
    initials_ok = all(any(s.startswith(t[0]) for s in subject_tokens)
                      for t in tokens if _INITIAL.match(t))
    part_of_subject = initials_ok and all(w in subject_tokens for w in words)
    contains_subject = subject_tokens <= set(words)
    return part_of_subject or contains_subject


# --- Soggetto IMPRESA nel testo (marcatore per il modello, non una redazione) ------
# Forme giuridiche scritte in coda al nome ("S.r.l.", "Srl", "S.p.A.", "soc. coop."…).
_LEGAL = (r"(?:s\.?\s?r\.?\s?l\.?(?:\s?s\.?)?|s\.?\s?p\.?\s?a\.?|s\.?\s?n\.?\s?c\.?|s\.?\s?a\.?\s?s\.?"
          r"|s\.?\s?c\.?\s?a\.?\s?r\.?\s?l\.?|soc(?:ietà|ieta)?\.?\s+coop(?:erativa)?\.?|coop\.?|onlus)")
_LEGAL_TAIL = re.compile(rf"(?:[\s,]+{_LEGAL})+\s*$", re.IGNORECASE)
# Parole comuni nelle denominazioni (stesse del worker, mention.GENERIC): "Tron Group
# Holding" negli articoli è spesso solo "Tron".
_GENERIC = {"GRUPPO", "GROUP", "HOLDING", "IMPRESA", "IMPRESE", "COSTRUZIONI", "INFRASTRUTTURE",
            "SERVIZI", "ITALIA", "ITALIANA", "GENERALE", "GENERALI", "LAVORI", "EDILE", "EDILIZIA",
            "IMPIANTI", "GESTIONE", "GESTIONI", "CONSORZIO", "ENERGIA", "AMBIENTE", "GLOBAL",
            "INTERNATIONAL"}


def _proper_forms(word: str) -> str:
    """La parola scritta da nome proprio: com'è, Maiuscola iniziale, TUTTA MAIUSCOLA."""
    forms = {word, word.upper(), word[:1].upper() + word[1:]}
    return "(?:" + "|".join(map(re.escape, sorted(forms, key=len, reverse=True))) + ")"


def mark_entity(text: str, name: str | None) -> tuple[str, int]:
    """Il soggetto IMPRESA nel testo → `[SOGGETTO]` (con la forma giuridica che segue).
    Non è una redazione — una denominazione non è un dato personale — ma dice al
    modello di chi valutare ruolo e fatti: senza, per un'impresa il modello non sa chi
    è il soggetto e giudica i protagonisti dell'articolo.

    Il nome senza forma giuridica: di più parole senza distinzione di maiuscole. Di una
    parola, scritto da nome proprio e — se non lo segue la forma giuridica — a metà
    frase ("la Vita Srl", "la Tron ha vinto"; non "la vita", né "Vita e morte" a inizio
    frase). Se il nome finisce con parole comuni ("Tron Group Holding") vale anche la
    parte distintiva ("Tron"), con le stesse regole e non seguita da un altro nome
    ("Tron Energia" è un'altra società)."""
    words = _LEGAL_TAIL.sub("", " ".join((name or "").split())).strip(" ,").split()
    out, count = text or "", 0
    if not words:
        return out, 0
    legal = rf"(?P<legal>,?\s+(?i:{_LEGAL})(?!\w))?"

    def mark(rx: re.Pattern, s: str, anywhere: bool) -> tuple[str, int]:
        hits = 0

        def repl(m: re.Match) -> str:
            nonlocal hits
            before = s[:m.start()].rstrip(" \t\"'«“‘(")
            mid_sentence = bool(before) and before[-1] not in ".!?:;\n"
            if not (anywhere or m.group("legal") or m.groupdict().get("own") or mid_sentence):
                return m.group(0)
            hits += 1
            # "… della Fami Srl. La procura": il punto di "Srl." chiude anche la frase
            after = s[m.end():].lstrip(" \t")
            ends = m.group(0).endswith(".") and (not after or after[0].isupper() or after[0] == "\n")
            return "[SOGGETTO]." if ends else "[SOGGETTO]"
        return rx.sub(repl, s), hits

    if len(words) > 1:
        full = re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + legal + r"(?!\w)", re.IGNORECASE)
        out, n = mark(full, out, anywhere=True)
    else:
        # non seguito da un altro nome ("la Fami Holding" è probabilmente un'altra società)
        out, n = mark(re.compile(r"(?<!\w)" + _proper_forms(words[0]) + legal + r"(?!\w)(?!\s+[A-ZÀ-Ý])"),
                      out, anywhere=False)
    count += n
    lead = list(words)
    while len(lead) > 1 and _norm(lead[-1]) in _GENERIC:
        lead.pop()
    if len(lead) < len(words) and len("".join(lead)) >= 3:
        tail = "|".join(_proper_forms(w) for w in words[len(lead):])
        short = re.compile(r"(?<!\w)" + r"\s+".join(_proper_forms(w) for w in lead)
                           + rf"(?P<own>(?:\s+(?:{tail}))+)?" + legal + r"(?!\w)(?!\s+[A-ZÀ-Ý])")
        out, n = mark(short, out, anywhere=False)
        count += n
    return out, count


def redact_persons(text: str, subject_name: str | None = None,
                   ner_persons: list[str] | None = None) -> tuple[str, dict]:
    """Redige i NOMI di persona (B1.1): il **soggetto** (se noto) → `[SOGGETTO]`,
    gli **altri** (dalla NER) → `[PERSONA]`. Un nome NER è il soggetto solo se è
    parte del suo nome o lo contiene (vedi `_names_same_person`).

    Ritorna `(testo, {"soggetto": n, "persona": n})`. NON solleva; senza NER
    redige comunque il nome noto del soggetto."""
    out = text or ""
    counts = {"soggetto": 0, "persona": 0}
    subj_variants = _name_variants(subject_name) if subject_name else []
    subj_forms = {_norm(v) for v in subj_variants}
    subj_tokens = {t for v in subj_variants for t in _norm(v).split()}

    def _is_subject(person: str) -> bool:
        return _norm(person) in subj_forms or _names_same_person(person, subj_tokens)

    # 1) Soggetto noto → [SOGGETTO] (anche senza NER).
    for v in subj_variants:
        out, n = re.subn(rf"\b{re.escape(v)}\b", "[SOGGETTO]", out, flags=re.IGNORECASE)
        counts["soggetto"] += n
    # 2) Persone dalla NER: soggetto (per token) → [SOGGETTO], altri → [PERSONA].
    for p in sorted(set(ner_persons or []), key=len, reverse=True):
        if not p.strip() or _norm(p).strip("[] ") in ("SOGGETTO", "PERSONA"):
            continue   # i marcatori stessi non sono nomi
        repl, key = ("[SOGGETTO]", "soggetto") if _is_subject(p) else ("[PERSONA]", "persona")
        out, n = re.subn(rf"\b{re.escape(p)}\b", repl, out)
        counts[key] += n
    return out, counts
