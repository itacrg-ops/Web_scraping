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
from app.normalize import clean_id, name_similarity, valid_identifier

# --- Registro dei soggetti noti (seed dimostrativo) ---
REGISTRY: list[dict] = [
    {
        "id": "R-ACME", "denominazione": "ACME Costruzioni S.r.l.",
        "cf_piva": "00743110157", "cup": ["E51B21000000001"], "ruolo": "impresa esecutrice",
    },
    {
        "id": "R-ACME-GEN", "denominazione": "ACME Costruzioni Generali S.r.l.",
        "cf_piva": "09876543217", "cup": ["E51B21000000009"], "ruolo": "impresa esecutrice",
    },
    {
        "id": "R-BETA", "denominazione": "Beta Infrastrutture S.p.A.",
        "cf_piva": "12345670159", "cup": ["B22C21000000002"], "ruolo": "beneficiario",
    },
]


def _match_record(r: dict) -> dict:
    return {"id": r["id"], "denominazione": r["denominazione"], "cf_piva": r["cf_piva"], "cup": r.get("cup", [])}


def resolve(subject: dict) -> dict:
    warnings: list[str] = []
    cf = clean_id(subject.get("cf_piva"))
    name = subject.get("denominazione", "")
    id_ok = valid_identifier(cf) if cf else False

    # 1) Deterministico su CF/P.IVA (unico percorso che supera il gate di default)
    if cf:
        if not id_ok:
            warnings.append("Identificatore CF/P.IVA formalmente non valido (checksum)")
        for r in REGISTRY:
            if clean_id(r["cf_piva"]) == cf:
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

    # 2) Analisi sul nome — NON supera il gate da sola (rischio omonimia),
    #    salvo `allow_name_only_resolution` con un unico candidato forte.
    scored = sorted(
        ({"record": r, "score": round(name_similarity(name, r["denominazione"]), 3)} for r in REGISTRY),
        key=lambda x: x["score"], reverse=True,
    )
    best = scored[0] if scored else None
    second = scored[1]["score"] if len(scored) > 1 else 0.0
    candidates = [
        {**_match_record(c["record"]), "score": c["score"]}
        for c in scored if c["score"] >= settings.name_candidate
    ]

    strong_unique = (
        best is not None
        and best["score"] >= settings.name_high
        and (best["score"] - second) >= settings.name_margin
        and len(candidates) == 1
    )
    if settings.allow_name_only_resolution and strong_unique:
        return {
            "resolved": True,
            "status": "resolved",
            "method": "probabilistico_nome",
            "confidence": best["score"],
            "identifier_valid": id_ok,
            "matched": _match_record(best["record"]),
            "candidates": candidates,
            "warnings": warnings + ["Risoluzione sul solo nome (nessun identificatore forte)"],
        }

    # 3) Gate NON superato → disambiguazione umana (abstain by default)
    if len(candidates) >= 2:
        status = "ambiguous"
    elif candidates:
        status = "needs_review"
    else:
        status = "unresolved"
    warnings.append(
        "Disambiguazione non conclusiva: richiesta revisione umana (nessun giudizio senza Entity Resolution)."
    )
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
