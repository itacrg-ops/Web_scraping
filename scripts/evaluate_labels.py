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

La rivalutazione si avvia anche dalla console (pagina Observability), che mostra lo
stesso report: la logica è in `services/api/app/evaluation.py`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

# La logica di valutazione è una sola, nell'API (che la usa per la rivalutazione on
# demand dalla console): qui si importa dal repository.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "services", "api"))

from app.evaluation import (  # noqa: E402,F401  (riesportate: le usano anche i test)
    ALTRO,
    CHIUSURA,
    ESCALATION,
    category_metrics,
    disposition_metrics,
    esito_changes,
    evaluate,
    mention_metrics,
    replay_report,
    replay_status,
    reviewer_agreement,
    rivalutati,
    wilson,
)

def load(path: str, tutti: bool = False) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    return [r for r in records if tutti or r["label"].get("affidabile")]


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


_ESITO = {ESCALATION: "escalation", CHIUSURA: "chiusura", ALTRO: "non deciso"}


def print_changes(changes: dict) -> None:
    """Casi il cui esito è cambiato (rispetto al revisore) con la versione attuale."""
    for kind, title in (("corretti", "Ora corretti"), ("peggiorati", "Ora sbagliati"),
                        ("altri", "Altri cambiamenti di esito")):
        if changes.get(kind):
            print(f"\n  {title}:")
            for c in changes[kind]:
                print(f"  · {c['subject']}: {_ESITO[c['prima']]} → {_ESITO[c['dopo']]} "
                      f"(revisore: {_ESITO[c['revisore']]})" + (f" — {c['motivo']}" if c.get("motivo") else ""))


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
    report = replay_report(records)
    before, after, status = report["prima"], report["dopo"], Counter(report["rivalutazione"])
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2, default=str)
        print()
    else:
        print_comparison(before, after, status)
        print_changes(report["cambiamenti"])
        print("\n=== Dettaglio con la versione attuale (dopo) ===\n")
        print_report(after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
