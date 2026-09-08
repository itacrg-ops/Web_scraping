"""Decodifica e coerenza del Codice Fiscale (persona fisica).

Il CF italiano (16 caratteri) codifica cognome, nome, data e sesso di nascita e il
comune (codice Belfiore). Qui lo si **decodifica** e si verifica la **coerenza**
con i dati anagrafici inseriti: un CF che non corrisponde a nome/cognome/data
segnala un errore di inserimento o un CF sbagliato per quel soggetto → mitiga
l'omonimia e i refusi.

Nota: la verifica del **luogo di nascita** rispetto al codice Belfiore richiede la
tabella comuni ISTAT/Belfiore (~8k voci): qui decodifichiamo il codice e ne
riconosciamo la natura (estero = inizia con Z), lasciando il match sul nome del
comune come estensione con tabella.
"""
from __future__ import annotations

from app.normalize import clean_id, valid_cf

_VOWELS = set("AEIOU")
# Lettera del mese di nascita → numero.
_MONTHS = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "H": 6,
           "L": 7, "M": 8, "P": 9, "R": 10, "S": 11, "T": 12}


def _letters(s: str) -> str:
    """Solo lettere A-Z, maiuscole, senza accenti/spazi (usa clean_id + drop cifre)."""
    return "".join(c for c in clean_id(s) if c.isalpha())


def _consonants(s: str) -> list[str]:
    return [c for c in s if c not in _VOWELS]


def surname_code(cognome: str) -> str:
    s = _letters(cognome)
    picked = _consonants(s) + [c for c in s if c in _VOWELS]
    return "".join((picked + ["X", "X", "X"])[:3])


def name_code(nome: str) -> str:
    s = _letters(nome)
    cons = _consonants(s)
    if len(cons) >= 4:
        picked = [cons[0], cons[2], cons[3]]
    else:
        picked = cons + [c for c in s if c in _VOWELS]
    return "".join((picked + ["X", "X", "X"])[:3])


def decode(cf: str) -> dict | None:
    """Decodifica il CF nei suoi campi. Ritorna None se non ha 16 caratteri."""
    c = clean_id(cf)
    if len(c) != 16:
        return None
    day_raw = c[9:11]
    try:
        d = int(day_raw)
    except ValueError:
        d = None
    female = d is not None and d > 40
    day = (d - 40) if female else d
    belfiore = c[11:15]
    return {
        "surname_code": c[0:3],
        "name_code": c[3:6],
        "year2": c[6:8],
        "month": _MONTHS.get(c[8]),
        "day": day,
        "sex": ("F" if female else "M") if d is not None else None,
        "belfiore": belfiore,
        "estero": belfiore[:1] == "Z",
        "checksum_valid": valid_cf(c),
    }


def check_consistency(cf: str, nome: str | None = None, cognome: str | None = None,
                      data_nascita: str | None = None) -> dict:
    """Verifica la coerenza tra il CF e i dati anagrafici inseriti.

    Ritorna {valid, checksum_valid, decoded, checks[], warnings[], consistent}.
    `checks` elenca i confronti effettuati (campo/ok/atteso/calcolato). `consistent`
    è False se un confronto EFFETTUATO fallisce (campi mancanti non contano)."""
    dec = decode(cf)
    if dec is None:
        return {"valid": False, "checksum_valid": False, "decoded": None,
                "checks": [], "warnings": ["Codice Fiscale non valido: attesi 16 caratteri."],
                "consistent": False}

    checks: list[dict] = []
    warnings: list[str] = []
    if not dec["checksum_valid"]:
        warnings.append("Carattere di controllo del CF non valido (possibile refuso).")

    if cognome and cognome.strip():
        exp = surname_code(cognome)
        ok = exp == dec["surname_code"]
        checks.append({"campo": "cognome", "ok": ok, "atteso_dal_cf": dec["surname_code"], "calcolato": exp})
        if not ok:
            warnings.append(f"Il cognome «{cognome}» non corrisponde al CF (CF: {dec['surname_code']}, "
                            f"atteso dal cognome: {exp}).")

    if nome and nome.strip():
        exp = name_code(nome)
        ok = exp == dec["name_code"]
        checks.append({"campo": "nome", "ok": ok, "atteso_dal_cf": dec["name_code"], "calcolato": exp})
        if not ok:
            warnings.append(f"Il nome «{nome}» non corrisponde al CF (CF: {dec['name_code']}, "
                            f"atteso dal nome: {exp}).")

    if data_nascita and data_nascita.strip():
        dob_ok, msg = _check_dob(dec, data_nascita.strip())
        checks.append({"campo": "data_nascita", "ok": dob_ok,
                       "cf": _cf_dob_str(dec), "inserita": data_nascita.strip()})
        if not dob_ok:
            warnings.append(msg)

    consistent = all(c["ok"] for c in checks) and dec["checksum_valid"]
    return {"valid": True, "checksum_valid": dec["checksum_valid"], "decoded": dec,
            "checks": checks, "warnings": warnings, "consistent": consistent}


def _cf_dob_str(dec: dict) -> str:
    m = f"{dec['month']:02d}" if dec["month"] else "??"
    d = f"{dec['day']:02d}" if dec["day"] else "??"
    return f"AA{dec['year2']}-{m}-{d} (sesso {dec['sex'] or '?'})"


def _check_dob(dec: dict, data_nascita: str) -> tuple[bool, str]:
    """Confronta la data inserita (YYYY-MM-DD) con quella codificata nel CF
    (anno a 2 cifre, mese, giorno). Il secolo non è nel CF: si confrontano le
    ultime 2 cifre dell'anno, il mese e il giorno."""
    parts = data_nascita.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return False, f"Data di nascita «{data_nascita}» non in formato YYYY-MM-DD."
    yyyy, mm, dd = int(parts[0]), int(parts[1]), int(parts[2])
    if (yyyy % 100) != int(dec["year2"]):
        return False, (f"Anno di nascita incoerente col CF (CF: ..{dec['year2']}, inserito: {yyyy}).")
    if dec["month"] != mm:
        return False, (f"Mese di nascita incoerente col CF (CF: {dec['month']}, inserito: {mm}).")
    if dec["day"] != dd:
        return False, (f"Giorno di nascita incoerente col CF (CF: {dec['day']}, inserito: {dd}).")
    return True, ""
