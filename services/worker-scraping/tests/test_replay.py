"""Test della rivalutazione del dataset (replay.py): snapshot e LLM simulati, il resto è
la logica vera del worker (estrazione, riconoscimento del soggetto, AMI, esito).

    python services/worker-scraping/tests/test_replay.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys

os.environ["NER_CORROBORATION"] = "false"   # niente llm-gateway per la NER
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import replay  # noqa: E402
import snapshot  # noqa: E402

PAGE = "<html><body><article><h1>{title}</h1><p>{body}</p></article></body></html>"
SNAPSHOTS = {
    "a.html": PAGE.format(title="Inchiesta appalti", body=(
        "La ACME Costruzioni S.r.l. è indagata per corruzione e turbativa d'asta negli appalti "
        "pubblici della regione. ") * 8),
    "b.html": PAGE.format(title="Altra società", body=(
        "La Beta Servizi ha inaugurato un nuovo impianto di riciclo dei materiali plastici. ") * 8),
}
CALLS: list[str] = []


def _load_html(bucket: str, key: str) -> str:
    if key not in SNAPSHOTS:
        raise FileNotFoundError(key)
    return SNAPSHOTS[key]


async def _llm(text: str, subject_name=None, subject_person=False) -> dict:
    CALLS.append(text)
    return {"fatf_categories": ["Corruption & Bribery"], "severity": "media", "role_analysis": "perpetratore",
            "method": "llm_dual", "confidence": 0.8}


async def _llm_down(text: str, subject_name=None, subject_person=False) -> dict:
    return {"fatf_categories": ["Money Laundering"], "method": "euristica_keyword",
            "fallback_reason": "llm-gateway HTTP 503"}


snapshot.load_html = _load_html
replay.classify_fatf = _llm


def _alert(**kw) -> dict:
    return {"id": "AL1", "subject": "ACME Costruzioni S.r.l.", "tipo_soggetto": "persona_giuridica",
            "cf_piva": "00743110157", "cup": [], "disposition": "AUTO_CHIUSO", "fatf_categories": [],
            "entity_resolution": {"matched": None}, **kw}


def _ev(eid: str, key: str | None, cred: str = "alta") -> dict:
    return {"id": eid, "url": f"https://www.testata-{eid}.it/art", "raw_key": key, "bucket": "b",
            "content_hash": "sha256:x", "fonte_credibilita": cred, "mentioned": None, "label": None}


def test_replay_uses_only_articles_citing_the_subject() -> None:
    CALLS.clear()
    res = asyncio.run(replay.replay_alert(_alert(), [_ev("e1", "a.html"), _ev("e2", "b.html")]))
    assert res["status"] == "ok", res
    assert res["evidence"]["e1"]["mentioned"] is True and res["evidence"]["e2"]["mentioned"] is False
    assert len(CALLS) == 1 and "ACME" in CALLS[0] and "Beta Servizi" not in CALLS[0]
    # AMI vero: severità media (68) × credibilità alta (1.05) × fonte unica (0.95) = 68 → escalation
    assert res["alert"]["ami_score"] == 68 and res["alert"]["disposition"] == "ESCALATION_I_LIVELLO"
    assert res["alert"]["fatf_categories"] == ["Corruption & Bribery"]
    assert res["alert"]["classification"]["method"] == "llm_dual"


def test_missing_snapshot_and_no_articles() -> None:
    res = asyncio.run(replay.replay_alert(_alert(), [_ev("e1", "a.html"), _ev("e3", "sparito.html"),
                                                     _ev("e4", None)]))
    assert res["status"] == "ok" and res["evidence"]["e1"]["mentioned"] is True
    assert "non leggibile" in res["evidence"]["e3"]["errore"] and "non disponibile" in res["evidence"]["e4"]["errore"]
    assert asyncio.run(replay.replay_alert(_alert(), []))["status"] == "non_rivalutabile"


def test_llm_down_stops_the_replay() -> None:
    replay.classify_fatf = _llm_down
    try:
        asyncio.run(replay.replay_alert(_alert(), [_ev("e1", "a.html")]))
        raise AssertionError("doveva fermarsi")
    except replay.LlmUnavailable as exc:
        assert "503" in str(exc)
    finally:
        replay.classify_fatf = _llm


def test_run_one_line_per_label_without_internal_fields() -> None:
    CALLS.clear()
    base = {"schema": "ams-case-label/1", "alert": _alert(), "evidence": [_ev("e1", "a.html")]}
    records = [{**base, "label": {"reviewer": "r1", "affidabile": True}},
               {**base, "label": {"reviewer": "r2", "affidabile": True}}]
    out = io.StringIO()
    counts = asyncio.run(replay.run(records, out=out))
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert counts == {"ok": 1} and len(CALLS) == 1                 # un alert, rivalutato una volta
    assert [x["label"]["reviewer"] for x in lines] == ["r1", "r2"]
    assert all(x["replay"]["status"] == "ok" and x["replay"]["eseguita"] for x in lines)
    for x in lines:                                                # minimizzazione come l'export
        assert "cf_piva" not in x["alert"] and "entity_resolution" not in x["alert"]
        assert all("raw_key" not in e and "bucket" not in e for e in x["evidence"])


def test_replay_all_reports_progress() -> None:
    seen: list[tuple[int, int]] = []

    async def progress(done: int, total: int) -> None:
        seen.append((done, total))

    records = [{"alert": _alert(id=aid), "evidence": [_ev(f"{aid}-e", "a.html")]} for aid in ("X1", "X2", "X1")]
    by_alert = asyncio.run(replay.replay_all(records, progress))
    assert set(by_alert) == {"X1", "X2"} and seen == [(1, 2), (2, 2)]


def test_activity_delivers_results_to_the_api() -> None:
    from temporalio.testing import ActivityEnvironment
    posted: list[tuple[str, dict]] = []
    beats: list = []

    async def load(solo_affidabili: bool) -> list[dict]:
        assert solo_affidabili is False
        return [{"alert": _alert(id="Y1"), "evidence": [_ev("y", "a.html")]}]

    async def post(path: str, body: dict, attempts: int = 1) -> None:
        posted.append((path, body))

    saved = (replay.load_cases, replay._post)
    replay.load_cases, replay._post = load, post
    env = ActivityEnvironment()
    env.on_heartbeat = lambda *d: beats.append(d)
    try:
        counts = asyncio.run(env.run(replay.replay_dataset, "R9", False))
        replay.classify_fatf = _llm_down                     # LLM giù: errore non ritentabile
        try:
            asyncio.run(env.run(replay.replay_dataset, "R9", False))
            raise AssertionError("doveva fermarsi")
        except replay.ApplicationError as exc:
            assert exc.non_retryable and "LLM non disponibile" in str(exc)
    finally:
        replay.load_cases, replay._post = saved
        replay.classify_fatf = _llm
    assert counts == {"ok": 1}
    assert [p for p, _ in posted[:3]] == ["/api/replay/R9/progress", "/api/replay/R9/progress",
                                          "/api/replay/R9/result"], posted
    assert posted[1][1] == {"done": 1, "total": 1} and posted[2][1]["status"] == "completed"
    assert posted[2][1]["results"]["Y1"]["status"] == "ok" and len(beats) >= 2
    json.dumps(posted[2][1])                                 # consegnabile così com'è


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
