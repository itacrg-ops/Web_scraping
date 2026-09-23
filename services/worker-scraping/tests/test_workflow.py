"""Test del workflow di screening sul test server di Temporal, con activity finte
(stessi nomi delle reali; `compute_ami` è quella vera, logica pura).

Verifica l'affidabilità end-to-end della pipeline:
- l'alert si salva PRIMA della pubblicazione SVI e l'esito SVI viene registrato;
- un rifiuto SVI terminale non viene ritentato e non fa fallire lo screening;
- una ricerca fallita / il ripiego a keyword producono ESITO_INCOMPLETO;
- un errore non gestito segna lo screening come `failed`;
- ER non superata → alert "skipped", nessuna pubblicazione.

Richiede le dipendenze del worker (temporalio, …); il test server di Temporal viene
scaricato al primo avvio (oppure: TEMPORAL_CLI_PATH=<binario temporal> per usare un
dev server locale già presente).
    python services/worker-scraping/tests/test_workflow.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from temporalio import activity  # noqa: E402
from temporalio.client import WorkflowFailureError  # noqa: E402
from temporalio.exceptions import ApplicationError  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

import activities  # noqa: E402
import workflows  # noqa: E402

ARTICLE = ("La ACME Costruzioni S.r.l. è finita al centro di un'inchiesta: l'amministratore è "
           "stato arrestato per corruzione e turbativa d'asta negli appalti pubblici. ") * 6


def _fakes(cfg: dict) -> tuple[list, list, dict]:
    """Activity finte configurabili. Ritorna (activities, log delle chiamate, stato)."""
    log: list = []
    st: dict = {"alerts": {}, "publish": 0, "search": 0}

    @activity.defn(name="resolve_entity")
    async def resolve_entity(subject: dict) -> dict:
        ok = cfg.get("resolved", True)
        return {"resolved": ok, "status": "resolved" if ok else "ambiguous", "matched": {}}

    @activity.defn(name="assess_risk_feed")
    async def assess_risk_feed(subject: dict):
        return None

    @activity.defn(name="search_articles")
    async def search_articles(subject: dict, options: dict) -> list:
        st["search"] += 1
        if cfg.get("search") == "fail":
            raise RuntimeError("gdelt: GDELT ha limitato le richieste (429)")
        return [{"url": "https://www.ansa.it/a"}]

    @activity.defn(name="annotate_credibility")
    async def annotate_credibility(urls: list) -> dict:
        return {u: {"domain": "ansa.it", "credibilita": "alta"} for u in urls}

    @activity.defn(name="fetch_source")
    async def fetch_source(url: str) -> dict:
        return {"url": url, "allowed": True, "final_url": url, "raw_key": "k", "content_hash": "h"}

    @activity.defn(name="render_source")
    async def render_source(url: str) -> dict:
        return {"url": url, "allowed": True, "raw_key": None}

    @activity.defn(name="extract_content")
    async def extract_content(raw: dict) -> dict:
        return {"text": ARTICLE, "source": raw["url"], "testata": "www.ansa.it",
                "provenance": {"content_hash": "h", "fetch_ts": "t", "warc_key": "w",
                               "raw_key": "k", "bucket": "b"}}

    @activity.defn(name="verify_subject_mention")
    async def verify_subject_mention(subject: dict, text: str) -> dict:
        if cfg.get("mention") == "variant":   # nome esatto assente, uno simile sì
            return {"mentioned": False, "matched": [], "context": [], "variants": ["ACME Costruzzioni"],
                    "anagraphics": {"status": "n/a"}, "ner": None}
        return {"mentioned": True, "matched": ["denominazione"], "context": [],
                "anagraphics": {"status": "n/a"}, "ner": None}

    @activity.defn(name="classify_fatf")
    async def classify_fatf(text: str, name: str | None, person: bool) -> dict:
        if cfg.get("classify") == "keyword":
            return {"fatf_categories": ["Corruption & Bribery"], "method": "euristica_keyword",
                    "fallback_reason": "llm-gateway HTTP 503"}
        return {"fatf_categories": ["Corruption & Bribery"], "method": "llm_dual", "severity": "alta"}

    @activity.defn(name="persist_alert")
    async def persist_alert(alert: dict) -> str:
        log.append(("persist", alert.get("svi_status")))
        if cfg.get("persist") == "fail":
            raise RuntimeError("API non raggiungibile")
        aid = f"A-{alert['screening_id']}"
        st["alerts"][aid] = dict(alert)
        return aid

    @activity.defn(name="publish_svi")
    async def publish_svi(payload: dict) -> str:
        st["publish"] += 1
        log.append("publish")
        if cfg.get("publish") == "reject":
            raise ApplicationError("SVI ha rifiutato l'alert: errorCode 1008", type="SviRejected",
                                   non_retryable=True)
        if cfg.get("publish") == "transient":
            raise RuntimeError("svi-publisher HTTP 502")
        return "svi-123"

    @activity.defn(name="update_alert_svi")
    async def update_alert_svi(alert_id: str, update: dict) -> None:
        log.append(("svi", update["svi_status"]))
        st["alerts"][alert_id].update(update)

    @activity.defn(name="mark_screening_failed")
    async def mark_screening_failed(screening_id: str, error: str) -> None:
        log.append(("failed", error))

    acts = [resolve_entity, assess_risk_feed, search_articles, annotate_credibility, fetch_source,
            render_source, extract_content, verify_subject_mention, classify_fatf,
            activities.compute_ami, persist_alert, publish_svi, update_alert_svi, mark_screening_failed]
    return acts, log, st


async def _screen(env: WorkflowEnvironment, cfg: dict) -> tuple[dict | Exception, list, dict]:
    acts, log, st = _fakes(cfg)
    queue, sid = f"q-{uuid.uuid4().hex[:8]}", f"S-{uuid.uuid4().hex[:8]}"
    req = {"screening_id": sid, "denominazione": "ACME Costruzioni S.r.l.",
           "tipo_soggetto": "persona_giuridica", "cf_piva": "00743110157"}
    async with Worker(env.client, task_queue=queue, workflows=[workflows.ScreeningWorkflow],
                      activities=acts):
        try:
            res: dict | Exception = await env.client.execute_workflow(
                workflows.ScreeningWorkflow.run, req, id=f"wf-{sid}", task_queue=queue)
        except WorkflowFailureError as exc:
            res = exc
    return res, log, st


def _alert(st: dict) -> dict:
    return next(iter(st["alerts"].values()))


async def test_persist_before_publish_and_record_outcome(env) -> None:
    res, log, st = await _screen(env, {})
    assert log == [("persist", "pending"), "publish", ("svi", "published")], log
    assert res["svi_status"] == "published" and res["disposition"] == "ESCALATION_I_LIVELLO"
    a = _alert(st)
    assert a["svi_alert_id"] == "svi-123"
    # predizioni salvate per il dataset di valutazione
    assert a["classification"]["method"] == "llm_dual" and a["classification"]["severity"] == "alta"
    assert a["evidence"][0]["mentioned"] is True
    assert a["evidence"][0]["mention_match"] == ["denominazione"]


async def test_terminal_svi_rejection_is_not_retried_and_screening_completes(env) -> None:
    res, log, st = await _screen(env, {"publish": "reject"})
    assert isinstance(res, dict), res                       # lo screening NON fallisce
    assert st["publish"] == 1, st["publish"]                # non-retryable: un solo tentativo
    assert res["svi_status"] == "failed" and "1008" in _alert(st)["svi_error"]
    assert not any(isinstance(e, tuple) and e[0] == "failed" for e in log)


async def test_transient_svi_failure_is_retried_then_recorded(env) -> None:
    res, log, st = await _screen(env, {"publish": "transient"})
    assert st["publish"] == 3, st["publish"]                # RetryPolicy(maximum_attempts=3)
    assert res["svi_status"] == "failed" and "502" in _alert(st)["svi_error"]


async def test_search_failure_is_incomplete_not_auto_closed(env) -> None:
    res, log, st = await _screen(env, {"search": "fail"})
    a = _alert(st)
    assert st["search"] == 3                                # ritentata da Temporal
    assert a["disposition"] == "ESITO_INCOMPLETO" and a["risk_level"] == "N/D", a["disposition"]
    assert a["drivers"][0].startswith("⚠ ESITO INCOMPLETO") and "429" in a["drivers"][0]
    assert not any("Nessun articolo trovato" in d for d in a["drivers"])
    assert "publish" in log                                 # resta visibile in SVI, marcato


async def test_keyword_fallback_is_incomplete(env) -> None:
    res, log, st = await _screen(env, {"classify": "keyword"})
    a = _alert(st)
    assert a["disposition"] == "ESITO_INCOMPLETO", a["disposition"]
    assert "parole chiave (llm-gateway HTTP 503)" in a["drivers"][0]


async def test_unhandled_failure_marks_screening_failed(env) -> None:
    res, log, st = await _screen(env, {"persist": "fail"})
    assert isinstance(res, WorkflowFailureError), res
    failed = [e for e in log if isinstance(e, tuple) and e[0] == "failed"]
    assert failed and "API non raggiungibile" in failed[0][1], log
    assert "publish" not in log                             # niente SVI senza record locale


async def test_similar_name_in_articles_is_flagged(env) -> None:
    res, log, st = await _screen(env, {"mention": "variant"})
    a = _alert(st)
    assert a["name_variants"] == ["ACME Costruzzioni"], a.get("name_variants")
    assert a["drivers"][0].startswith("⚠ Negli articoli compare un nome simile: «ACME Costruzzioni»")
    ok, _, st2 = await _screen(env, {})
    assert _alert(st2)["name_variants"] == []                   # nome esatto trovato: nessun avviso


async def test_unresolved_entity_is_skipped_not_published(env) -> None:
    res, log, st = await _screen(env, {"resolved": False})
    assert res["resolved"] is False
    assert log == [("persist", "skipped")], log


async def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    # TEMPORAL_CLI_PATH = binario `temporal` già presente (rete senza temporal.download):
    # dev server locale; altrimenti test server scaricato automaticamente.
    cli = os.getenv("TEMPORAL_CLI_PATH")
    env_ctx = (await WorkflowEnvironment.start_local(dev_server_existing_path=cli) if cli
               else await WorkflowEnvironment.start_time_skipping())
    async with env_ctx as env:
        for fn in tests:
            try:
                await fn(env)
                print(f"PASS {fn.__name__}")
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print(f"FAIL {fn.__name__}: {exc!r}"[:400])
    print(f"\n{len(tests) - fails}/{len(tests)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
