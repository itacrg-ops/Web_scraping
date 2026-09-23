#!/usr/bin/env python3
"""Valuta il sistema sul dataset etichettato dai revisori (export NDJSON della console,
pagina Alert → «Esporta dataset»).

Uso (dalla root del repo, solo libreria standard):

  python scripts/evaluate_labels.py dataset-casi-20260923.ndjson
  python scripts/evaluate_labels.py dataset.ndjson --tutti    # include le bozze
  python scripts/evaluate_labels.py dataset.ndjson --json     # output per altri strumenti

Con il file della **rivalutazione** (worker `replay.py`: gli stessi casi ripassati nella
versione attuale del sistema) il report mette a confronto «prima» (predizione salvata a
suo tempo) e «dopo» (versione attuale):

  python scripts/evaluate_labels.py rivalutazione.ndjson

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
                errors.append({"subject": r["alert"]["subject"], "sistema": pred, "revisore": attesa,
                               "ruolo": r["label"].get("ruolo"),
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


def _dec(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _fmt(w: dict) -> str:
    if w["rate"] is None:
        return "n/d (nessun caso)"
    lo, hi = w["ci95"]
    return f"{w['rate']:.0%} ({w['k']}/{w['n']}, IC95% {lo:.0%}–{hi:.0%})"


def print_report(rep: dict) -> None:
    print(f"Casi valutati: {rep['casi']} (soggetti distinti: {rep['soggetti']})")
    if rep["casi"] < 30:
        print("  ⚠ campione piccolo: le percentuali sono solo indicative (vedi intervalli).")
    if rep["soggetti"] < rep["casi"]:
        print("  ⚠ più casi dello stesso soggetto: non sono indipendenti, gli intervalli sono ottimisti.")
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
    print(f"  per caso: sistema {_dec(c['per_caso']['sistema'])} · revisore {_dec(c['per_caso']['revisore'])}")
    for cat, v in c["per_categoria"].items():
        print(f"  {cat}: tp {v['tp']} · fp {v['fp']} · fn {v['fn']}")
    e = rep["esito"]
    print("\nEsito (per caso)")
    print(f"  accordo {_fmt(e['accordo'])}")
    print(f"  falsi negativi (da escalation ma chiusi) {_fmt(e['falsi_negativi'])}")
    print(f"  falsi positivi (da chiudere ma escalati) {_fmt(e['falsi_positivi'])}")
    print(f"  non decisi dal sistema (incompleti/HITL): {e['non_decisi_dal_sistema']}")
    for err in e["errori"][:15]:
        kind = "falso negativo" if err["sistema"] == CHIUSURA else "falso positivo"
        print(f"  ✗ {err['subject']}: {kind} (ruolo per il revisore: {err['ruolo'] or '—'}; "
              f"categorie del sistema: {', '.join(err['categorie']) or '—'})")
    if rep["accordo_revisori"]["n"]:
        print(f"\nAccordo tra revisori sull'esito: {_fmt(rep['accordo_revisori'])}")
    print("\nPer metodo di classificazione")
    for method, g in rep["per_metodo"].items():
        casi = f"{g['casi']} {'caso' if g['casi'] == 1 else 'casi'}"
        print(f"  {method} ({casi}): menzione {_fmt(g['menzione'])} · "
              f"categorie {_fmt(g['categorie']['precisione'])} · esito {_fmt(g['esito'])}")


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


def _short(w: dict) -> str:
    return "n/d" if w["rate"] is None else f"{w['rate']:.0%} ({w['k']}/{w['n']})"


def print_comparison(before: dict, after: dict, status: Counter) -> None:
    labels = {"ok": "rivalutati", "non_rivalutabile": "senza articoli (invariati)", "errore": "in errore (invariati)"}
    print("Rivalutazione con la versione attuale: "
          + ", ".join(f"{n} {labels.get(s, s)}" for s, n in sorted(status.items())))
    rows = [
        ("Riconoscimento", "precisione", _short(before["menzione"]["precisione"]), _short(after["menzione"]["precisione"])),
        ("", "richiamo", _short(before["menzione"]["richiamo"]), _short(after["menzione"]["richiamo"])),
        ("Categorie", "precisione", _short(before["categorie"]["micro"]["precisione"]),
         _short(after["categorie"]["micro"]["precisione"])),
        ("", "richiamo", _short(before["categorie"]["micro"]["richiamo"]), _short(after["categorie"]["micro"]["richiamo"])),
        ("", "per caso", _dec(before["categorie"]["per_caso"]["sistema"]),
         _dec(after["categorie"]["per_caso"]["sistema"])),
        ("Esito", "accordo", _short(before["esito"]["accordo"]), _short(after["esito"]["accordo"])),
        ("", "falsi negativi", _short(before["esito"]["falsi_negativi"]), _short(after["esito"]["falsi_negativi"])),
        ("", "falsi positivi", _short(before["esito"]["falsi_positivi"]), _short(after["esito"]["falsi_positivi"])),
        ("", "non decisi", str(before["esito"]["non_decisi_dal_sistema"]), str(after["esito"]["non_decisi_dal_sistema"])),
    ]
    print(f"\n  {'':<15}{'':<16}{'prima':<18}dopo")
    for group, metric, b, a in rows:
        print(f"  {group:<15}{metric:<16}{b:<18}{a}")
    cats = sorted(set(before["categorie"]["per_categoria"]) | set(after["categorie"]["per_categoria"]))
    changed = [(c, before["categorie"]["per_categoria"].get(c), after["categorie"]["per_categoria"].get(c)) for c in cats]
    lines = [f"  {c}: fp {b['fp'] if b else 0} → {a['fp'] if a else 0} · fn {b['fn'] if b else 0} → {a['fn'] if a else 0}"
             for c, b, a in changed if (b or {}).get("fp") != (a or {}).get("fp") or (b or {}).get("fn") != (a or {}).get("fn")]
    if lines:
        print("\n  Categorie cambiate (prima → dopo):")
        print("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dataset", help="export NDJSON della console, o il file della rivalutazione")
    ap.add_argument("--tutti", action="store_true", help="includi anche i casi non marcati affidabili")
    ap.add_argument("--json", action="store_true", help="stampa il report in JSON")
    args = ap.parse_args(argv)
    records = load(args.dataset, tutti=args.tutti)
    if not any("replay" in r for r in records):
        rep = evaluate(records)
        if args.json:
            json.dump(rep, sys.stdout, ensure_ascii=False, indent=2, default=str)
            print()
        else:
            print_report(rep)
        return 0
    before, after, status = evaluate(records), evaluate(rivalutati(records)), replay_status(records)
    if args.json:
        json.dump({"rivalutazione": dict(status), "prima": before, "dopo": after},
                  sys.stdout, ensure_ascii=False, indent=2, default=str)
        print()
    else:
        print_comparison(before, after, status)
        print("\n=== Dettaglio con la versione attuale (dopo) ===\n")
        print_report(after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
