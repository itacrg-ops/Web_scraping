"""Valutazione del sistema sul dataset etichettato dai revisori: predizione del sistema
contro giudizio umano (i giudizi "incerto" sono esclusi), anche separatamente per metodo
di classificazione (LLM / parole chiave).

- **Riconoscimento del soggetto** (per articolo): il sistema lo ritiene citato
  (`mentioned`) contro il revisore ("si" = citato; "omonimo"/"non_citato" = no), anche
  per tipo di corrispondenza (nome_cognome, denominazione, denominazione_breve…).
- **Categorie FATF** (per caso): predette contro corrette, per categoria.
- **Esito** (per caso): disposition del sistema contro disposition attesa. I falsi
  negativi (il revisore dice escalation, il sistema chiude) sono l'errore più grave.

Con la **rivalutazione** (worker `replay.py`: gli stessi casi ripassati nella versione
attuale) si confrontano «prima» (predizione salvata a suo tempo) e «dopo».

Solo libreria standard: lo usano l'API (rivalutazione on demand dalla console, pagina
Observability) e `scripts/evaluate_labels.py` (riga di comando). Con pochi casi le
percentuali oscillano molto: ogni tasso ha l'intervallo di confidenza al 95% (Wilson).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

ESCALATION, CHIUSURA, ALTRO = "ESCALATION", "CHIUSURA", "ALTRO"
_PRED = {"ESCALATION_I_LIVELLO": ESCALATION, "AUTO_CHIUSO": CHIUSURA}


def wilson(k: int, n: int, z: float = 1.96) -> dict:
    """Tasso k/n con intervallo di confidenza di Wilson (None se n = 0)."""
    if n == 0:
        return {"k": 0, "n": 0, "rate": None, "ci95": None}
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return {"k": k, "n": n, "rate": round(p, 3), "ci95": [round(centre - half, 3), round(centre + half, 3)]}


def _prf(tp: int, fp: int, fn: int) -> dict:
    return {"tp": tp, "fp": fp, "fn": fn,
            "precisione": wilson(tp, tp + fp), "richiamo": wilson(tp, tp + fn)}


def mention_metrics(records: list[dict]) -> dict:
    tp = fp = fn = tn = 0
    by_match: dict[str, Counter] = defaultdict(Counter)
    errors = []
    for r in records:
        for e in r.get("evidence", []):
            truth = (e.get("label") or {}).get("pertinenza")
            if truth in (None, "incerto") or e.get("mentioned") is None:
                continue
            real, pred = truth == "si", bool(e["mentioned"])
            tp, fp, fn, tn = tp + (pred and real), fp + (pred and not real), fn + (real and not pred), tn + (not pred and not real)
            for kind in (e.get("mention_match") or []) if pred else []:
                by_match[kind]["corrette" if real else "errate"] += 1
            if pred != real:
                errors.append({"alert_id": r["alert"].get("id"), "subject": r["alert"]["subject"],
                               "url": e.get("url"), "sistema": pred, "revisore": truth,
                               "match": e.get("mention_match")})
    return {**_prf(tp, fp, fn), "tn": tn,
            "per_tipo_di_match": {k: wilson(c["corrette"], c["corrette"] + c["errate"])
                                  for k, c in sorted(by_match.items())},
            "errori": errors}


def category_metrics(records: list[dict]) -> dict:
    per_cat: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        pred, truth = set(r["alert"].get("fatf_categories") or []), set(r["label"].get("categorie_corrette") or [])
        for c in pred | truth:
            per_cat[c]["tp" if c in pred and c in truth else "fp" if c in pred else "fn"] += 1
    tot = Counter()
    for c in per_cat.values():
        tot.update(c)
    n = len(records) or 1
    return {"micro": _prf(tot["tp"], tot["fp"], tot["fn"]),
            # quante categorie per caso: un sistema che ne mette molte ha richiamo alto e precisione bassa
            "per_caso": {"sistema": round(sum(len(r["alert"].get("fatf_categories") or []) for r in records) / n, 2),
                         "revisore": round(sum(len(r["label"].get("categorie_corrette") or []) for r in records) / n, 2)},
            "per_categoria": {c: _prf(v["tp"], v["fp"], v["fn"]) for c, v in sorted(per_cat.items())}}


def disposition_metrics(records: list[dict]) -> dict:
    matrix: dict[str, Counter] = {ESCALATION: Counter(), CHIUSURA: Counter()}
    errors = []
    for r in records:
        attesa = {"ESCALATION_I_LIVELLO": ESCALATION, "AUTO_CHIUSO": CHIUSURA}.get(r["label"].get("disposition_attesa"))
        if attesa:
            pred = _PRED.get(r["alert"].get("disposition"), ALTRO)
            matrix[attesa][pred] += 1
            if pred not in (attesa, ALTRO):
                errors.append({"alert_id": r["alert"].get("id"), "subject": r["alert"]["subject"],
                               "sistema": pred, "revisore": attesa, "ruolo": r["label"].get("ruolo"),
                               "categorie": r["alert"].get("fatf_categories") or []})
    esc, chi = matrix[ESCALATION], matrix[CHIUSURA]
    decisi = esc[ESCALATION] + esc[CHIUSURA] + chi[ESCALATION] + chi[CHIUSURA]
    return {
        "matrice (riga = revisore, colonna = sistema)": {k: dict(v) for k, v in matrix.items()},
        "accordo": wilson(esc[ESCALATION] + chi[CHIUSURA], decisi),
        # errore più grave: casi da escalation che il sistema ha chiuso
        "falsi_negativi": wilson(esc[CHIUSURA], esc[ESCALATION] + esc[CHIUSURA]),
        "falsi_positivi": wilson(chi[ESCALATION], chi[ESCALATION] + chi[CHIUSURA]),
        "non_decisi_dal_sistema": esc[ALTRO] + chi[ALTRO],   # ESITO_INCOMPLETO, HITL…
        "errori": errors,
    }


def reviewer_agreement(records: list[dict]) -> dict:
    """Accordo tra revisori sulla disposition attesa, dove lo stesso caso ne ha più d'uno."""
    per_alert: dict[str, list[str]] = defaultdict(list)
    for r in records:
        if r["label"].get("disposition_attesa"):
            per_alert[r["alert"]["id"]].append(r["label"]["disposition_attesa"])
    multi = [v for v in per_alert.values() if len(v) > 1]
    return wilson(sum(len(set(v)) == 1 for v in multi), len(multi))


def evaluate(records: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[((r["alert"].get("classification") or {}).get("method")) or "sconosciuto"].append(r)
    report = {"casi": len(records),
              # casi dello stesso soggetto non sono indipendenti: gli intervalli li trattano come tali
              "soggetti": len({" ".join(r["alert"]["subject"].upper().split()) for r in records}),
              "menzione": mention_metrics(records),
              "categorie": category_metrics(records), "esito": disposition_metrics(records),
              "accordo_revisori": reviewer_agreement(records), "per_metodo": {}}
    for method, recs in sorted(groups.items()):
        report["per_metodo"][method] = {"casi": len(recs), "menzione": mention_metrics(recs)["precisione"],
                                        "categorie": category_metrics(recs)["micro"],
                                        "esito": disposition_metrics(recs)["accordo"]}
    return report



# --- Rivalutazione (replay.py): «prima» contro «dopo» -------------------------------
def rivalutati(records: list[dict]) -> list[dict]:
    """Vista «dopo»: la predizione rivalutata al posto di quella salvata. I casi non
    rivalutabili (senza articoli) o in errore restano come erano."""
    out = []
    for r in records:
        rep = r.get("replay") or {}
        if rep.get("status") != "ok":
            out.append(r)
            continue
        new_ev = rep.get("evidence") or {}
        out.append({**r, "alert": {**r["alert"], **rep["alert"]},
                    "evidence": [{**e, "mentioned": (new_ev.get(e.get("id")) or {}).get("mentioned"),
                                  "mention_match": (new_ev.get(e.get("id")) or {}).get("mention_match")}
                                 for e in r.get("evidence", [])]})
    return out


def replay_status(records: list[dict]) -> Counter:
    """Esito della rivalutazione per caso (ok / non_rivalutabile / errore)."""
    return Counter(({r["alert"]["id"]: (r.get("replay") or {}).get("status", "assente") for r in records}).values())


def _esito(alert: dict) -> str:
    return _PRED.get(alert.get("disposition"), ALTRO)


def esito_changes(records: list[dict]) -> dict:
    """Casi il cui esito è cambiato con la rivalutazione, rispetto al revisore:
    «corretti» (ora giusti), «peggiorati» (prima giusti, ora no), «altri» (per esempio
    da non deciso a sbagliato). `motivo`: il primo punto della nuova motivazione."""
    out: dict[str, list[dict]] = {"corretti": [], "peggiorati": [], "altri": []}
    seen = set()
    for r, after in zip(records, rivalutati(records)):
        attesa = _PRED.get(r["label"].get("disposition_attesa"))
        prima, dopo = _esito(r["alert"]), _esito(after["alert"])
        if not attesa or prima == dopo:
            continue
        item = {"alert_id": r["alert"].get("id"), "subject": r["alert"]["subject"], "prima": prima,
                "dopo": dopo, "revisore": attesa, "motivo": (after["alert"].get("drivers") or [None])[0]}
        key = (item["alert_id"], attesa)
        if key in seen:        # più revisori con lo stesso giudizio: una riga
            continue
        seen.add(key)
        kind = "corretti" if dopo == attesa else "peggiorati" if prima == attesa else "altri"
        out[kind].append(item)
    return out


def replay_report(records: list[dict]) -> dict:
    """Report della rivalutazione: esito per caso, metriche prima e dopo, cambiamenti."""
    return {"rivalutazione": dict(replay_status(records)), "prima": evaluate(records),
            "dopo": evaluate(rivalutati(records)), "cambiamenti": esito_changes(records)}
