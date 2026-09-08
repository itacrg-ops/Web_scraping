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
from app import codice_fiscale, semantic


def _match_record(r: dict) -> dict:
    return {
        "id": r["id"],
        "tipo": r.get("tipo", PERSONA_GIURIDICA),
        "denominazione": r["denominazione"],
        "cf_piva": r.get("cf_piva"),
        "cup": r.get("cup", []),
        "ruolo": r.get("ruolo"),
        "data_nascita": r.get("data_nascita"),
        "luogo_nascita": r.get("luogo_nascita"),
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

    # 0) Coerenza CF ↔ dati anagrafici inseriti (persona fisica). Il CF codifica
    #    cognome, nome e data di nascita: se non corrispondono a quanto inserito,
    #    l'input è contraddittorio (refuso o CF errato per il soggetto) → non si
    #    procede a un match autoritativo. Il checksum non blocca (solo avviso).
    if cf and is_person and len(cf) == 16:
        nome_in = (subject.get("nome") or "").strip()
        cognome_in = (subject.get("cognome") or "").strip()
        if not (nome_in or cognome_in):
            toks = _subject_name(subject).split()
            if toks:
                cognome_in, nome_in = toks[0], " ".join(toks[1:])
        cf_cons = codice_fiscale.check_consistency(cf, nome_in, cognome_in, dob)
        if cf_cons["checks"] and any(not c["ok"] for c in cf_cons["checks"]):
            return {
                "resolved": False,
                "status": "needs_review",
                "method": "incoerenza_CF_dati_anagrafici",
                "confidence": 0.4,
                "identifier_valid": id_ok,
                "matched": None,
                "candidates": [],
                "warnings": warnings + cf_cons["warnings"] + [
                    "Dati anagrafici incoerenti col Codice Fiscale: verifica CF, nome, "
                    "cognome o data di nascita."
                ],
            }
        warnings += cf_cons["warnings"]  # es. avviso di checksum non valido (non bloccante)

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
    scored = [{"record": r, "score": round(similarity(name, r["denominazione"]), 3)} for r in pool]

    # Embedding (B7): fonde una componente semantica nella similarità del nome
    # (varianti/abbreviazioni che la stringa sottostima). Opt-in e NON fatale:
    # senza embedding configurati resta la sola similarità di stringa.
    if settings.use_embeddings and pool and name:
        emb = semantic.similarities(name, [r["denominazione"] for r in pool])
        if emb is not None and len(emb) == len(pool):
            w = settings.embedding_weight
            for item, e in zip(scored, emb):
                item["score"] = round((1 - w) * item["score"] + w * e, 3)
            warnings.append("Similarità semantica (embedding) fusa nel matching del nome")

    scored.sort(key=lambda x: x["score"], reverse=True)
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

    # 2b-bis) Disambiguazione per luogo di nascita (persona fisica): ulteriore
    #         restringimento tra omonimi quando indicato.
    if is_person and candidates_scored:
        luogo = " ".join((subject.get("luogo_nascita") or "").upper().split())
        if luogo:
            same_luogo = [c for c in candidates_scored
                          if " ".join((c["record"].get("luogo_nascita") or "").upper().split()) == luogo]
            if same_luogo and len(same_luogo) < len(candidates_scored):
                candidates_scored = same_luogo
                warnings.append("Candidati ristretti per luogo di nascita")
            elif not same_luogo:
                warnings.append("Nessun candidato con il luogo di nascita indicato (possibile omonimia)")

    # 2c) Disambiguazione per CUP dell'intervento (B7): tra candidati OMONIMI il
    #     legame autoritativo persona↔CUP nel registro individua quello giusto.
    #     Non è "solo nome": è nome + legame forte allo specifico intervento.
    if settings.allow_cup_disambiguation and candidates_scored:
        req_cups = {clean_id(c) for c in (subject.get("cup") or []) if clean_id(c)}
        if req_cups:
            def _rec_cups(item: dict) -> set:
                return {clean_id(x) for x in (item["record"].get("cup") or []) if clean_id(x)}
            cup_matches = [c for c in candidates_scored if req_cups & _rec_cups(c)]
            if len(cup_matches) == 1:
                rec = cup_matches[0]["record"]
                cup_hit = sorted(req_cups & _rec_cups(cup_matches[0]))[0]
                return {
                    "resolved": True,
                    "status": "resolved",
                    "method": "probabilistico_nome_CUP",
                    "confidence": round(max(cup_matches[0]["score"], 0.9), 3),
                    "identifier_valid": id_ok,
                    "matched": _match_record(rec),
                    "candidates": [],
                    "warnings": warnings + [
                        f"Disambiguazione per CUP dell'intervento ({cup_hit}): tra gli omonimi "
                        "a registro individuato univocamente il soggetto legato a questo CUP."
                    ],
                }
            if len(cup_matches) >= 2:
                candidates_scored = cup_matches
                warnings.append(
                    "Candidati ristretti per CUP dell'intervento (restano omonimi sullo stesso CUP)"
                )

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
