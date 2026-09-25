"""Rivalutazione del dataset etichettato con la versione ATTUALE del sistema.

Per ogni caso etichettato ripassa gli articoli già salvati (snapshot su object store,
nessuna nuova ricerca né fetch) nella pipeline di oggi: estrazione del testo,
riconoscimento del soggetto, classificazione FATF (llm-gateway), feed di rischio,
AMI ed esito. Scrive su stdout lo stesso NDJSON dell'export della console, con in più
la sezione `replay` (la nuova predizione); `scripts/evaluate_labels.py` mette a
confronto la predizione salvata a suo tempo («prima») e quella rivalutata («dopo»).
Così ogni modifica si misura sugli stessi casi, senza ripetere screening ed etichette.

Uso (dove girano i servizi; i log vanno su stderr):

  docker compose -f docker-compose.dev.yml exec -T worker-scraping \\
      python replay.py > rivalutazione.ndjson
  python scripts/evaluate_labels.py rivalutazione.ndjson

  --tutti      anche i casi in bozza (default: solo i casi affidabili)
  --limite N   solo i primi N casi (prova veloce)

Il file contiene dati personali come l'export (senza CF/P.IVA): stesse cautele.
Si ferma se l'LLM non risponde: una rivalutazione a parole chiave non misurerebbe il
sistema reale. La classificazione LLM (temperatura 0) può variare di poco tra due
esecuzioni.

La stessa rivalutazione si avvia dalla console (pagina Observability): l'API avvia il
workflow `ReplayWorkflow`, che esegue l'activity `replay_dataset` qui sotto; il report
prima/dopo lo calcola l'API.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

import snapshot
from activities import (
    API_BASE,
    INTERNAL_API_TOKEN,
    assess_risk_feed,
    classify_fatf,
    compute_ami,
    extract_content,
    verify_subject_mention,
)
from analysis import ami_signals, classification_text, merge_risk_feed, saved_classification
from outcome import apply_incomplete, incomplete_reasons

# Campi usati per rivalutare ma da non riscrivere nel file (minimizzazione, come l'export).
_INTERNAL_ALERT = ("cf_piva", "entity_resolution")
_INTERNAL_EVIDENCE = ("bucket", "raw_key")


class LlmUnavailable(RuntimeError):
    """La classificazione è ripiegata sulle parole chiave: rivalutazione non significativa."""


class ReplayError(RuntimeError):
    """Casi da rivalutare non disponibili (API)."""


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


async def load_cases(solo_affidabili: bool) -> list[dict]:
    headers = {"X-Internal-Token": INTERNAL_API_TOKEN} if INTERNAL_API_TOKEN else None
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{API_BASE}/api/labels/replay",
                             params={"solo_affidabili": str(solo_affidabili).lower()}, headers=headers)
    if r.status_code in (401, 503):
        raise ReplayError(f"API {r.status_code}: INTERNAL_API_TOKEN del worker mancante o diverso da quello dell'API")
    if r.status_code != 200:
        raise ReplayError(f"API {r.status_code}: casi etichettati non disponibili")
    return r.json()["records"]


def subject_of(alert: dict) -> dict:
    """Il soggetto come lo vede il workflow. Data e luogo di nascita dal registro, se
    l'Entity Resolution l'aveva trovato; nome/cognome e qualificatori della richiesta
    originale non sono conservati (per la persona fisica vale "Cognome Nome")."""
    matched = (alert.get("entity_resolution") or {}).get("matched") or {}
    return {
        "tipo_soggetto": alert.get("tipo_soggetto") or "persona_giuridica",
        "denominazione": alert["subject"], "nome": None, "cognome": None,
        "data_nascita": matched.get("data_nascita"), "luogo_nascita": matched.get("luogo_nascita"),
        "cf_piva": alert.get("cf_piva"), "azienda": None, "localita": None, "ruolo": None,
        "cup": alert.get("cup") or [],
    }


async def replay_alert(alert: dict, evidence: list[dict]) -> dict:
    """Nuova predizione per un alert, dagli articoli salvati. Stessi passi e stesse
    funzioni del workflow (activities.py, analysis.py, outcome.py)."""
    if not evidence:
        return {"status": "non_rivalutabile", "motivo": "nessun articolo salvato"}
    subject = subject_of(alert)
    docs: list[dict] = []
    per_article: dict[str, dict] = {}
    for ev in evidence:
        if not ev.get("raw_key"):
            per_article[ev["id"]] = {"errore": "snapshot non disponibile"}
            continue
        raw = {"url": ev.get("url"), "final_url": ev.get("url"), "raw_key": ev["raw_key"],
               "bucket": ev.get("bucket") or snapshot.BUCKET, "content_hash": ev.get("content_hash"),
               "fetch_ts": ev.get("fetch_ts"), "warc_key": ev.get("warc_key")}
        try:
            doc = await extract_content(raw)
        except Exception as exc:  # noqa: BLE001 — snapshot rimosso/illeggibile: si va avanti
            per_article[ev["id"]] = {"errore": f"snapshot non leggibile ({type(exc).__name__})"}
            continue
        men = await verify_subject_mention(subject, doc.get("text", ""))
        doc.update(_mentioned=bool(men.get("mentioned")), _matched=men.get("matched", []),
                   _credibilita=ev.get("fonte_credibilita"), _domain=None)
        docs.append(doc)
        per_article[ev["id"]] = {"mentioned": doc["_mentioned"], "mention_match": doc["_matched"],
                                 "caratteri": len(doc.get("text") or "")}

    combined = classification_text(docs)
    if combined:
        classification = await classify_fatf(combined, subject["denominazione"],
                                             subject["tipo_soggetto"] == "persona_fisica")
        if classification.get("fallback_reason"):
            raise LlmUnavailable(classification["fallback_reason"])
    else:
        classification = {"fatf_categories": [], "method": "nessun_contenuto"}
    risk_feed = await assess_risk_feed(subject)
    if risk_feed and risk_feed.get("available"):
        classification = merge_risk_feed(classification, risk_feed)
    ami = await compute_ami(subject, classification, ami_signals(docs))
    outcome = apply_incomplete(
        {"ami_score": ami["ami_score"], "risk_level": ami["risk_level"],
         "disposition": ami["disposition"], "drivers": ami["drivers"]},
        incomplete_reasons(search_error=None, urls=[d.get("source") for d in docs],
                           docs_with_text=sum(1 for d in docs if d.get("text")),
                           classification=classification, risk_feed=risk_feed),
    )
    return {
        "status": "ok",
        "alert": {"ami_score": outcome["ami_score"], "risk_level": outcome["risk_level"],
                  "disposition": outcome["disposition"],
                  "fatf_categories": classification.get("fatf_categories", []),
                  "classification": saved_classification(classification),
                  "drivers": outcome["drivers"]},
        "evidence": per_article,
    }


def _public(record: dict) -> dict:
    """Il record come nell'export: senza i campi interni usati per rivalutare."""
    alert = {k: v for k, v in record["alert"].items() if k not in _INTERNAL_ALERT}
    evidence = [{k: v for k, v in e.items() if k not in _INTERNAL_EVIDENCE} for e in record["evidence"]]
    return {**record, "alert": alert, "evidence": evidence}


Progress = Callable[[int, int], Awaitable[None]]


async def replay_all(records: list[dict], progress: Progress | None = None) -> dict[str, dict]:
    """Rivaluta ogni alert una volta (più revisori = più righe, stessa predizione):
    alert_id → nuova predizione. `progress(fatti, totale)` dopo ogni caso."""
    by_alert: dict[str, dict] = {}
    alert_ids = list(dict.fromkeys(r["alert"]["id"] for r in records))
    for i, aid in enumerate(alert_ids, 1):
        rec = next(r for r in records if r["alert"]["id"] == aid)
        _log(f"[{i}/{len(alert_ids)}] {rec['alert']['subject']} — {len(rec['evidence'])} articoli")
        try:
            by_alert[aid] = await replay_alert(rec["alert"], rec["evidence"])
        except LlmUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — un caso in errore non ferma gli altri
            by_alert[aid] = {"status": "errore", "motivo": f"{type(exc).__name__}: {exc}"[:300]}
        if by_alert[aid]["status"] != "ok":
            _log(f"    {by_alert[aid]['status']}: {by_alert[aid]['motivo']}")
        if progress:
            await progress(i, len(alert_ids))
    return by_alert


async def run(records: list[dict], out=None) -> dict:
    """Riga di comando: NDJSON dell'export + sezione `replay`. Ritorna i conteggi."""
    out = out or sys.stdout
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    by_alert = await replay_all(records)
    for r in records:
        out.write(json.dumps({**_public(r), "replay": {**by_alert[r["alert"]["id"]], "eseguita": started}},
                             ensure_ascii=False, default=str) + "\n")
    counts: dict[str, int] = {}
    for res in by_alert.values():
        counts[res["status"]] = counts.get(res["status"], 0) + 1
    return counts


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tutti", action="store_true", help="anche i casi in bozza")
    ap.add_argument("--limite", type=int, default=0, help="solo i primi N casi")
    args = ap.parse_args(argv)
    try:
        records = await load_cases(solo_affidabili=not args.tutti)
    except ReplayError as exc:
        _log(f"ERRORE: {exc}")
        return 2
    if args.limite:
        keep = list(dict.fromkeys(r["alert"]["id"] for r in records))[: args.limite]
        records = [r for r in records if r["alert"]["id"] in keep]
    if not records:
        _log("Nessun caso etichettato da rivalutare.")
        return 0
    try:
        counts = await run(records)
    except LlmUnavailable as exc:
        _log(f"ERRORE: classificazione LLM non disponibile ({exc}). Rivalutazione interrotta: "
             "a parole chiave non misurerebbe il sistema reale. Controlla llm-gateway e riprova.")
        return 2
    _log("Fatto: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
         + ". Ora: python scripts/evaluate_labels.py <file>")
    return 0


# --- On demand dalla console (pagina Observability) -------------------------------------
def _headers() -> dict | None:
    return {"X-Internal-Token": INTERNAL_API_TOKEN} if INTERNAL_API_TOKEN else None


async def _post(path: str, body: dict, attempts: int = 1) -> None:
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(f"{API_BASE}{path}", json=body, headers=_headers())
            r.raise_for_status()
            return
        except Exception:  # noqa: BLE001 — si riprova, poi l'errore sale
            if attempt == attempts:
                raise
            await asyncio.sleep(2 * attempt)


@activity.defn
async def replay_dataset(run_id: str, solo_affidabili: bool = True) -> dict:
    """Rivaluta i casi etichettati e consegna all'API la nuova predizione per caso (che
    ne calcola il report). Avanzamento all'API e heartbeat a Temporal dopo ogni caso."""
    try:
        records = await load_cases(solo_affidabili)
    except ReplayError as exc:
        raise ApplicationError(str(exc), type="ReplayError", non_retryable=True) from exc

    async def progress(done: int, total: int) -> None:
        activity.heartbeat(done)
        try:
            await _post(f"/api/replay/{run_id}/progress", {"done": done, "total": total})
        except Exception as exc:  # noqa: BLE001 — l'avanzamento è informativo
            _log(f"avanzamento non registrato ({type(exc).__name__}): si prosegue")

    await progress(0, len({r["alert"]["id"] for r in records}))
    try:
        by_alert = await replay_all(records, progress)
    except LlmUnavailable as exc:
        raise ApplicationError(
            f"classificazione LLM non disponibile ({exc}): rivalutazione interrotta, a parole chiave "
            "non misurerebbe il sistema reale. Controlla llm-gateway e riprova.",
            type="LlmUnavailable", non_retryable=True) from exc
    await _post(f"/api/replay/{run_id}/result", {"status": "completed", "results": by_alert}, attempts=3)
    return dict(Counter(res["status"] for res in by_alert.values()))


@activity.defn
async def replay_failed(run_id: str, error: str) -> None:
    """Registra sulla rivalutazione il motivo per cui si è fermata."""
    await _post(f"/api/replay/{run_id}/result", {"status": "failed", "error": error[:2000]}, attempts=3)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
