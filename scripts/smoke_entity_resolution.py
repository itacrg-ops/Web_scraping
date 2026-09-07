#!/usr/bin/env python3
"""Smoke-test del gate anti-omonimia (Entity Resolution §8).

Interroga `POST /resolve` con i casi noti del registro seed (i due omonimi
"Rossi Mario" e le due "ACME Costruzioni") e verifica l'esito atteso:
resolved / ambiguous / needs_review, incluso il conflitto CF↔data di nascita.

Uso (dalla root del repo):

  # con Python sull'host (il servizio pubblica la porta 8070):
  python scripts/smoke_entity_resolution.py

  # senza Python sull'host — dentro un container sulla rete di compose:
  docker run --rm --network adverse-media_default -e ER_URL=http://entity-resolution:8070 \
      -v "${PWD}/scripts:/s" python:3.11-alpine python /s/smoke_entity_resolution.py

Variabile d'ambiente:
  ER_URL   base URL del servizio (default http://localhost:8070)

Nota: i casi assumono il REGISTRO SEED di default. Se hai modificato il registro
dalla console (tab Soggetti), gli esiti possono cambiare: rilancia dopo aver
ripristinato il seed, oppure adegua le attese qui sotto.

Exit code: 0 tutti PASS · 1 almeno un FAIL · 2 servizio non raggiungibile.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

ER_URL = os.environ.get("ER_URL", "http://localhost:8070").rstrip("/")
TIMEOUT = 15

# Ogni caso: subject inviato + esito atteso. Le attese riflettono il comportamento
# del resolver sul registro seed (verificato: coincide con docs/SVILUPPO_LOCALE.md).
CASES: list[dict] = [
    {
        "label": "PF Rossi Mario — solo nome/cognome",
        "subject": {"tipo_soggetto": "persona_fisica", "nome": "Mario", "cognome": "Rossi"},
        "expect": {"status": "ambiguous", "min_candidates": 2},
        "why": "due omonimi a registro, nessun discriminante → gate NON superato",
    },
    {
        "label": "PF Rossi Mario + data 1975-03-15 (senza CF)",
        "subject": {"tipo_soggetto": "persona_fisica", "nome": "Mario", "cognome": "Rossi",
                    "data_nascita": "1975-03-15"},
        "expect": {"status": "needs_review"},
        "why": "la data restringe a 1, ma il solo nome non supera il gate",
    },
    {
        "label": "PF CF RSSMRA80E20F205I (senza data)",
        "subject": {"tipo_soggetto": "persona_fisica", "nome": "Mario", "cognome": "Rossi",
                    "cf_piva": "RSSMRA80E20F205I"},
        "expect": {"status": "resolved", "matched_id": "R-ROSSI-2",
                   "method_contains": "deterministico"},
        "why": "identificatore forte (CF) → disambigua l'omonimo",
    },
    {
        "label": "PF CF RSSMRA80E20F205I + data 1980-05-20 (coerente)",
        "subject": {"tipo_soggetto": "persona_fisica", "nome": "Mario", "cognome": "Rossi",
                    "cf_piva": "RSSMRA80E20F205I", "data_nascita": "1980-05-20"},
        "expect": {"status": "resolved", "matched_id": "R-ROSSI-2"},
        "why": "CF + data coerente → resolved",
    },
    {
        "label": "PF CF RSSMRA80E20F205I + data 1975-03-15 (DISCORDANTE)",
        "subject": {"tipo_soggetto": "persona_fisica", "nome": "Mario", "cognome": "Rossi",
                    "cf_piva": "RSSMRA80E20F205I", "data_nascita": "1975-03-15"},
        "expect": {"status": "needs_review", "method_contains": "conflitto"},
        "why": "il CF è del nato nel 1980, ma è indicato 1975 → incoerenza",
    },
    {
        "label": "PG ACME Costruzioni — solo nome",
        "subject": {"tipo_soggetto": "persona_giuridica", "denominazione": "ACME Costruzioni"},
        "expect": {"status": "ambiguous", "min_candidates": 2},
        "why": "esiste anche 'ACME Costruzioni Generali' → ambiguo",
    },
    {
        "label": "PG ACME Costruzioni + P.IVA 00743110157",
        "subject": {"tipo_soggetto": "persona_giuridica", "denominazione": "ACME Costruzioni",
                    "cf_piva": "00743110157"},
        "expect": {"status": "resolved", "matched_id": "R-ACME",
                   "method_contains": "deterministico"},
        "why": "P.IVA → resolved",
    },
]


def _post_resolve(subject: dict) -> dict:
    data = json.dumps(subject).encode("utf-8")
    req = urllib.request.Request(
        f"{ER_URL}/resolve", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _check(res: dict, expect: dict) -> list[str]:
    """Ritorna la lista di scostamenti dall'atteso (vuota = PASS)."""
    fails: list[str] = []
    if res.get("status") != expect["status"]:
        fails.append(f"status={res.get('status')} (atteso {expect['status']})")
    if "matched_id" in expect:
        got = (res.get("matched") or {}).get("id")
        if got != expect["matched_id"]:
            fails.append(f"matched={got} (atteso {expect['matched_id']})")
    if "method_contains" in expect and expect["method_contains"] not in (res.get("method") or ""):
        fails.append(f"method={res.get('method')} (atteso ~{expect['method_contains']})")
    if "min_candidates" in expect and len(res.get("candidates") or []) < expect["min_candidates"]:
        fails.append(f"candidati={len(res.get('candidates') or [])} (attesi ≥{expect['min_candidates']})")
    return fails


def main() -> int:
    print(f"Smoke-test Entity Resolution (gate anti-omonimia) → {ER_URL}/resolve\n")
    # Prima chiamata: se il servizio non risponde, messaggio chiaro ed esci.
    try:
        _post_resolve(CASES[0]["subject"])
    except urllib.error.URLError as exc:
        print(f"✖ Servizio non raggiungibile su {ER_URL}: {exc.reason}")
        print("  Avvia lo stack:  docker compose -f docker-compose.dev.yml up -d entity-resolution api")
        print("  oppure imposta ER_URL (es. http://entity-resolution:8070 dentro la rete Docker).")
        return 2

    passed = 0
    for c in CASES:
        try:
            res = _post_resolve(c["subject"])
        except Exception as exc:  # noqa: BLE001
            print(f"✖ ERRORE  {c['label']}: {type(exc).__name__}: {exc}")
            continue
        fails = _check(res, c["expect"])
        matched = (res.get("matched") or {}).get("denominazione") or "—"
        ncand = len(res.get("candidates") or [])
        tag = "✔ PASS" if not fails else "✖ FAIL"
        if not fails:
            passed += 1
        print(f"{tag}  {c['label']}")
        print(f"        → status={res.get('status')} · method={res.get('method')} · "
              f"matched={matched} · candidati={ncand}")
        if fails:
            print(f"        ✖ scostamenti: {'; '.join(fails)}")

    total = len(CASES)
    print(f"\nRisultato: {passed}/{total} PASS")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
