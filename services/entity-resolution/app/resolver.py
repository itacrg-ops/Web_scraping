"""Logica di Entity Resolution (anti-omonimia).

Gate obbligatorio prima del giudizio (§8 del capitolato). Strategia:
  1) match **deterministico** su CF/P.IVA (identificatore forte) → confidence 1.0;
  2) in mancanza, match **probabilistico** sul nome normalizzato, con soglie e
     margine dal secondo candidato;
  3) altrimenti **ambiguo** (più candidati) o **irrisolto** → il gate NON è
     superato: si escala alla disambiguazione umana (abstain by default).

Il "registro" qui è un seed in memoria; in produzione proviene da
ReGiS/OpenCoesione/InfoCamere (beneficiari/attuatori/UBO).
TODO: NER (BERT) e similarità su embedding per i casi senza identificatore.
"""
from __future__ import annotations

from app.config import settings
from app.normalize import (
    clean_id,
    name_similarity,
    person_name_similarity,
    valid_identifier,
)
from app.registry import PERSONA_FISICA, PERSONA_GIURIDICA, get_registry


def _match_record(r: dict) -> dict:
    return {
        "id": r["id"],
        "tipo": r.get("tipo", PERSONA_GIURIDICA),
        "denominazione": r["denominazione"],
        "cf_piva": r.get("cf_piva"),
        "cup": r.get("cup", []),
        "ruolo": r.get("ruolo"),
        "data_nascita": r.get("data_nascita"),
    }


def _is_person(subject: dict) -> bool:
    return (subject.get("tipo_soggetto") or PERSONA_GIURIDICA).strip() == PERSONA_FISICA


def _subject_name(subject: dict) -> str:
    """Nome su cui fare il matching: la denominazione, o — per la persona fisica
    priva di denominazione — la composizione 'Cognome Nome'."""
    name = (subject.get("denominazione") or "").strip()
    if name:
        return name
    parts = [subject.get("cognome"), subject.get("nome")]
    return " ".join(p for p in parts if p).strip()


def resolve(subject: dict) -> dict:
    warnings: list[str] = []
    reg = get_registry()  # registro corrente (dall'API, con cache/fallback)
    cf = clean_id(subject.get("cf_piva"))
    is_person = _is_person(subject)
    name = _subject_name(subject)
    dob = (subject.get("data_nascita") or "").strip() or None
    id_ok = valid_identifier(cf) if cf else False
    similarity = person_name_similarity if is_person else name_similarity

    # 1) Deterministico su CF/P.IVA (unico percorso che supera il gate di default).
    #    Gli identificatori sono globalmente univoci (CF 16 char = persona fisica,
    #    P.IVA 11 = persona giuridica), quindi il match vale per entrambi i tipi.
    if cf:
        if not id_ok:
            warnings.append("Identificatore CF/P.IVA formalmente non valido (checksum)")
        for r in reg:
            if clean_id(r.get("cf_piva")) == cf:
                rec_dob = r.get("data_nascita")
                # Coerenza CF ↔ data di nascita: se entrambe presenti ma
                # discordanti, l'input è contraddittorio (o è errato il CF, o la
                # data). Non superare il gate: revisione umana (abstain).
                if dob and rec_dob and dob != rec_dob:
                    return {
                        "resolved": False,
                        "status": "needs_review",
                        "method": "conflitto_CF_data_nascita",
                        "confidence": 0.5,
                        "identifier_valid": id_ok,
                        "matched": None,
                        "candidates": [{**_match_record(r), "score": None}],
                        "warnings": warnings + [
                            f"Incoerenza CF/data di nascita: il CF corrisponde a "
                            f"{r['denominazione']} (nato/a {rec_dob}), ma è stata indicata "
                            f"la data {dob}. Verifica manuale richiesta."
                        ],
                    }
                return {
                    "resolved": True,
                    "status": "resolved",
                    "method": "deterministico_CF_PIVA",
                    "confidence": 1.0 if id_ok else 0.85,
                    "identifier_valid": id_ok,
                    "matched": _match_record(r),
                    "candidates": [],
                    "warnings": warnings,
                }
        warnings.append("CF/P.IVA non presente nel registro dei soggetti noti")

    # 2) Analisi sul nome — confrontando SOLO i record dello stesso tipo del
    #    soggetto (una persona non va confrontata con una società).
    target_tipo = PERSONA_FISICA if is_person else PERSONA_GIURIDICA
    pool = [r for r in reg if r.get("tipo", PERSONA_GIURIDICA) == target_tipo]
    scored = sorted(
        ({"record": r, "score": round(similarity(name, r["denominazione"]), 3)} for r in pool),
        key=lambda x: x["score"], reverse=True,
    )
    best = scored[0] if scored else None
    second = scored[1]["score"] if len(scored) > 1 else 0.0
    candidates_scored = [c for c in scored if c["score"] >= settings.name_candidate]

    # 2b) Disambiguazione per data di nascita (solo persona fisica): se indicata,
    #     restringe ai candidati con la stessa data → riduce l'omonimia.
    dob_used = False
    if is_person and dob and candidates_scored:
        same_dob = [c for c in candidates_scored if c["record"].get("data_nascita") == dob]
        if same_dob:
            candidates_scored = same_dob
            dob_used = True
            warnings.append("Candidati ristretti per data di nascita")
        else:
            warnings.append("Nessun candidato con la data di nascita indicata (possibile omonimia)")

    candidates = [{**_match_record(c["record"]), "score": c["score"]} for c in candidates_scored]

    strong_unique = (
        best is not None
        and best["score"] >= settings.name_high
        and (best["score"] - second) >= settings.name_margin
        and len(candidates) == 1
    )
    # Per la persona fisica il solo nome è ancora più esposto all'omonimia:
    # ammetti il name-only solo se c'è anche la data di nascita a disambiguare.
    name_only_ok = settings.allow_name_only_resolution and strong_unique and (not is_person or dob_used)
    if name_only_ok:
        note = "Risoluzione sul solo nome (nessun identificatore forte)"
        if dob_used:
            note += " + data di nascita"
        return {
            "resolved": True,
            "status": "resolved",
            "method": "probabilistico_nome_dob" if dob_used else "probabilistico_nome",
            "confidence": best["score"],
            "identifier_valid": id_ok,
            "matched": _match_record(best["record"]),
            "candidates": candidates,
            "warnings": warnings + [note],
        }

    # 3) Gate NON superato → disambiguazione umana (abstain by default)
    if len(candidates) >= 2:
        status = "ambiguous"
    elif candidates:
        status = "needs_review"
    else:
        status = "unresolved"

    # Modalità ESPLORATIVA (default OFF): soggetto non a registro (nessun
    # candidato) → risoluzione PROVVISORIA, non autoritativa, per esercitare
    # comunque la pipeline. Non tocca i casi ambigui (lì serve disambiguare).
    if status == "unresolved" and settings.allow_unregistered_subject:
        return {
            "resolved": True,
            "status": "provvisorio",
            "method": "non_a_registro",
            "confidence": 0.3,
            "identifier_valid": id_ok,
            "matched": None,
            "candidates": [],
            "warnings": warnings + [
                "Soggetto NON presente nel registro dei soggetti noti: screening "
                "ESPLORATIVO (non autoritativo). Identità e pertinenza all'intervento "
                "(CUP) da verificare manualmente."
            ],
        }

    hint = (
        "Disambiguazione non conclusiva: richiesta revisione umana "
        "(nessun giudizio senza Entity Resolution)."
    )
    if is_person and status in ("ambiguous", "needs_review"):
        hint += " Per la persona fisica indicare il Codice Fiscale (16 caratteri) o la data di nascita."
    warnings.append(hint)
    return {
        "resolved": False,
        "status": status,
        "method": "nessuno",
        "confidence": best["score"] if best else 0.0,
        "identifier_valid": id_ok,
        "matched": None,
        "candidates": candidates,
        "warnings": warnings,
    }
