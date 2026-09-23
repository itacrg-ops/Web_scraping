#!/usr/bin/env python3
"""Valuta il sistema sul dataset etichettato dai revisori (export NDJSON della console,
pagina Alert → «Esporta dataset»).

Uso (dalla root del repo, solo libreria standard):

  python scripts/evaluate_labels.py dataset-casi-20260923.ndjson
  python scripts/evaluate_labels.py dataset.ndjson --tutti    # include le bozze
  python scripts/evaluate_labels.py dataset.ndjson --json     # output per altri strumenti

Confronta la predizione del sistema con il giudizio umano (i giudizi "incerto" sono
esclusi), anche separatamente per metodo di classificazione (LLM / parole chiave):

- **Riconoscimento del soggetto** (per articolo): il sistema lo ritiene citato
  (`mentioned`) contro il revisore ("si" = citato; "omonimo"/"non_citato" = no), anche
  per tipo di corrispondenza (nome_cognome, denominazione, denominazione_breve…).
- **Categorie FATF** (per caso): predette contro corrette, per categoria.
- **Esito** (per caso): disposition del sistema contro disposition attesa. I falsi
  negativi (il revisore dice escalation, il sistema chiude) sono l'errore più grave.

Con pochi casi le percentuali oscillano molto: per questo ogni tasso ha l'intervallo di
confidenza al 95% (Wilson).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
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


def load(path: str, tutti: bool = False) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    return [r for r in records if tutti or r["label"].get("affidabile")]


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
                errors.append({"subject": r["alert"]["subject"], "url": e.get("url"), "sistema": pred,
                               "revisore": truth, "match": e.get("mention_match")})
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
    return {"micro": _prf(tot["tp"], tot["fp"], tot["fn"]),
            "per_categoria": {c: _prf(v["tp"], v["fp"], v["fn"]) for c, v in sorted(per_cat.items())}}


def disposition_metrics(records: list[dict]) -> dict:
    matrix: dict[str, Counter] = {ESCALATION: Counter(), CHIUSURA: Counter()}
    for r in records:
        attesa = {"ESCALATION_I_LIVELLO": ESCALATION, "AUTO_CHIUSO": CHIUSURA}.get(r["label"].get("disposition_attesa"))
        if attesa:
            matrix[attesa][_PRED.get(r["alert"].get("disposition"), ALTRO)] += 1
    esc, chi = matrix[ESCALATION], matrix[CHIUSURA]
    decisi = esc[ESCALATION] + esc[CHIUSURA] + chi[ESCALATION] + chi[CHIUSURA]
    return {
        "matrice (riga = revisore, colonna = sistema)": {k: dict(v) for k, v in matrix.items()},
        "accordo": wilson(esc[ESCALATION] + chi[CHIUSURA], decisi),
        # errore più grave: casi da escalation che il sistema ha chiuso
        "falsi_negativi": wilson(esc[CHIUSURA], esc[ESCALATION] + esc[CHIUSURA]),
        "falsi_positivi": wilson(chi[ESCALATION], chi[ESCALATION] + chi[CHIUSURA]),
        "non_decisi_dal_sistema": esc[ALTRO] + chi[ALTRO],   # ESITO_INCOMPLETO, HITL…
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
    report = {"casi": len(records), "menzione": mention_metrics(records),
              "categorie": category_metrics(records), "esito": disposition_metrics(records),
              "accordo_revisori": reviewer_agreement(records), "per_metodo": {}}
    for method, recs in sorted(groups.items()):
        report["per_metodo"][method] = {"casi": len(recs), "menzione": mention_metrics(recs)["precisione"],
                                        "categorie": category_metrics(recs)["micro"],
                                        "esito": disposition_metrics(recs)["accordo"]}
    return report


def _fmt(w: dict) -> str:
    if w["rate"] is None:
        return "n/d (nessun caso)"
    lo, hi = w["ci95"]
    return f"{w['rate']:.0%} ({w['k']}/{w['n']}, IC95% {lo:.0%}–{hi:.0%})"


def print_report(rep: dict) -> None:
    print(f"Casi valutati: {rep['casi']}")
    if rep["casi"] < 30:
        print("  ⚠ campione piccolo: le percentuali sono solo indicative (vedi intervalli).")
    m = rep["menzione"]
    print("\nRiconoscimento del soggetto (per articolo)")
    print(f"  precisione {_fmt(m['precisione'])} · richiamo {_fmt(m['richiamo'])}")
    for kind, w in m["per_tipo_di_match"].items():
        print(f"  corrette per match «{kind}»: {_fmt(w)}")
    for err in m["errori"][:10]:
        print(f"  ✗ {err['subject']}: sistema={'citato' if err['sistema'] else 'non citato'}, "
              f"revisore={err['revisore']} ({err['url']})")
    c = rep["categorie"]
    print("\nCategorie FATF (per caso)")
    print(f"  micro: precisione {_fmt(c['micro']['precisione'])} · richiamo {_fmt(c['micro']['richiamo'])}")
    for cat, v in c["per_categoria"].items():
        print(f"  {cat}: tp {v['tp']} · fp {v['fp']} · fn {v['fn']}")
    e = rep["esito"]
    print("\nEsito (per caso)")
    print(f"  accordo {_fmt(e['accordo'])}")
    print(f"  falsi negativi (da escalation ma chiusi) {_fmt(e['falsi_negativi'])}")
    print(f"  falsi positivi (da chiudere ma escalati) {_fmt(e['falsi_positivi'])}")
    print(f"  non decisi dal sistema (incompleti/HITL): {e['non_decisi_dal_sistema']}")
    if rep["accordo_revisori"]["n"]:
        print(f"\nAccordo tra revisori sull'esito: {_fmt(rep['accordo_revisori'])}")
    print("\nPer metodo di classificazione")
    for method, g in rep["per_metodo"].items():
        casi = f"{g['casi']} {'caso' if g['casi'] == 1 else 'casi'}"
        print(f"  {method} ({casi}): menzione {_fmt(g['menzione'])} · "
              f"categorie {_fmt(g['categorie']['precisione'])} · esito {_fmt(g['esito'])}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dataset", help="export NDJSON della console")
    ap.add_argument("--tutti", action="store_true", help="includi anche i casi non marcati affidabili")
    ap.add_argument("--json", action="store_true", help="stampa il report in JSON")
    args = ap.parse_args(argv)
    rep = evaluate(load(args.dataset, tutti=args.tutti))
    if args.json:
        json.dump(rep, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_report(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
