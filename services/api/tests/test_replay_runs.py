"""Rivalutazione del dataset on demand (pagina Observability): avvio del workflow, una
alla volta, avanzamento e report prima/dopo calcolato dall'API, ruoli. Temporal
simulato. Richiedono PostgreSQL:

    TEST_DATABASE_URL=postgresql://… python services/api/tests/test_replay_runs.py

(senza TEST_DATABASE_URL vengono SALTATI e lo dichiarano).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

DB_URL = os.getenv("TEST_DATABASE_URL", "")
if DB_URL:
    os.environ["DATABASE_URL"] = DB_URL  # prima di importare app.* (engine creato all'import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TOKEN = "tok-replay"
H = {"X-Internal-Token": TOKEN}
STARTED: list[tuple] = []


class _FakeTemporal:
    async def start_workflow(self, name, payload, id, task_queue):  # noqa: A002 — firma di Temporal
        STARTED.append((name, payload, id, task_queue))


async def _fake_client():
    return _FakeTemporal()


async def _down():
    raise ConnectionError("temporal giù")


async def _labeled_alert(client, subject: str, disposition: str, attesa: str) -> dict:
    from app.db import SessionLocal
    from app.models import Screening
    sid = f"RR-{uuid.uuid4().hex[:12]}"
    async with SessionLocal() as s:
        s.add(Screening(id=sid, denominazione=subject, status="running"))
        await s.commit()
    r = await client.post("/api/alerts", headers=H, json={
        "screening_id": sid, "subject": subject, "ami_score": 70, "risk_level": "MEDIO",
        "disposition": disposition, "fatf_categories": ["Organized Crime"],
        "classification": {"method": "llm_dual"},
        "evidence": [{"url": f"https://www.ansa.it/{sid}", "content_hash": sid, "mentioned": True,
                      "mention_match": ["nome_cognome"]}]})
    assert r.status_code == 201, r.text
    a = r.json()
    ev = a["evidence"][0]["id"]
    r = await client.put(f"/api/alerts/{a['id']}/label", json={
        "evidence_labels": {ev: {"pertinenza": "si", "avversa": "si"}}, "categorie_corrette": ["Organized Crime"],
        "ruolo": "autore_indagato", "disposition_attesa": attesa, "affidabile": True})
    assert r.status_code == 200, r.text
    return a


def _replayed(disposition: str, driver: str) -> dict:
    return {"status": "ok", "alert": {"ami_score": 25, "risk_level": "BASSO", "disposition": disposition,
                                      "fatf_categories": ["Organized Crime"],
                                      "classification": {"method": "llm_dual"}, "drivers": [driver]},
            "evidence": {}}


async def test_full_run(client) -> None:
    from app.routers import replay
    replay.get_client = _fake_client
    dead = await _labeled_alert(client, "Provenzano Bernardo", "ESCALATION_I_LIVELLO", "AUTO_CHIUSO")
    boss = await _labeled_alert(client, "Rossi Mario", "ESCALATION_I_LIVELLO", "ESCALATION_I_LIVELLO")
    STARTED.clear()
    r = await client.post("/api/replay", json={"solo_affidabili": True})
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "running" and run["started_by_name"]
    assert STARTED == [("ReplayWorkflow", {"run_id": run["id"], "solo_affidabili": True}, f"replay-{run['id']}",
                        "scraping")]
    # una alla volta
    assert (await client.post("/api/replay", json={})).status_code == 409
    # avanzamento: solo dal worker (token interno)
    url = f"/api/replay/{run['id']}"
    assert (await client.post(f"{url}/progress", json={"done": 1, "total": 2})).status_code == 401
    assert (await client.post(f"{url}/progress", json={"done": 1, "total": 2}, headers=H)).status_code == 204
    got = (await client.get(url)).json()
    assert (got["done"], got["total"], got["report"]) == (1, 2, None)
    # esito: Provenzano ora chiuso (giusto), Rossi ora chiuso (sbagliato)
    results = {dead["id"]: _replayed("AUTO_CHIUSO", "Chiuso: secondo gli articoli il soggetto è deceduto"),
               boss["id"]: _replayed("AUTO_CHIUSO", "Chiuso: fatti non recenti")}
    r = await client.post(f"{url}/result", headers=H, json={"status": "completed", "results": results})
    assert r.status_code == 200, r.text
    got = (await client.get(url)).json()
    assert got["status"] == "completed" and got["counts"] == {"ok": 2} and got["done"] == 2
    rep = got["report"]
    assert rep["prima"]["casi"] == 2 and rep["dopo"]["casi"] == 2      # solo i casi rivalutati
    ch = rep["cambiamenti"]
    assert [(c["alert_id"], c["motivo"]) for c in ch["corretti"]] == [
        (dead["id"], "Chiuso: secondo gli articoli il soggetto è deceduto")], ch
    assert [c["alert_id"] for c in ch["peggiorati"]] == [boss["id"]], ch
    assert rep["dopo"]["esito"]["falsi_negativi"]["k"] == 1 and rep["prima"]["esito"]["falsi_positivi"]["k"] == 1
    listed = next(x for x in (await client.get("/api/replay")).json() if x["id"] == run["id"])
    assert "report" not in listed and listed["sintesi"]["accordo"] == [0.5, 0.5], listed
    assert listed["sintesi"]["corretti"] == 1 and listed["sintesi"]["peggiorati"] == 1
    # consegna ripetuta: nessun cambiamento
    again = await client.post(f"{url}/result", headers=H, json={"status": "failed", "error": "tardi"})
    assert again.json()["status"] == "completed"


async def test_failure_and_temporal_down(client) -> None:
    from app.routers import replay
    replay.get_client = _fake_client
    run = (await client.post("/api/replay", json={"solo_affidabili": False})).json()
    r = await client.post(f"/api/replay/{run['id']}/result", headers=H,
                          json={"status": "failed", "error": "classificazione LLM non disponibile"})
    assert r.json()["status"] == "failed" and "LLM" in r.json()["error"]
    replay.get_client = _down
    r = await client.post("/api/replay", json={})
    assert r.status_code == 503, r.text
    failed = (await client.get("/api/replay")).json()[0]
    assert failed["status"] == "failed" and "orchestratore" in failed["error"]


async def test_stale_run_does_not_block(client) -> None:
    from app.db import SessionLocal
    from app.models import ReplayRun
    from app.routers import replay
    replay.get_client = _fake_client
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    async with SessionLocal() as s:
        s.add(ReplayRun(id=f"RR-{uuid.uuid4().hex[:8]}", status="running", solo_affidabili=True,
                        started_by="x", created_at=old, updated_at=old))
        await s.commit()
    r = await client.post("/api/replay", json={})
    assert r.status_code == 202, r.text
    stale = [x for x in (await client.get("/api/replay")).json() if x["id"].startswith("RR-")]
    assert stale and stale[0]["status"] == "failed" and "interrotta" in stale[0]["error"]


async def test_roles(client) -> None:
    from app.config import settings
    saved = settings.dataset_export_roles
    settings.dataset_export_roles = ["ruolo-che-nessuno-ha"]
    try:
        assert (await client.get("/api/replay")).status_code == 403
        assert (await client.post("/api/replay", json={})).status_code == 403
    finally:
        settings.dataset_export_roles = saved


async def _cleanup() -> None:
    from sqlalchemy import delete, select

    from app.db import SessionLocal
    from app.models import Alert, CaseLabel, Evidence, ReplayRun, Screening
    async with SessionLocal() as s:
        ids = (await s.execute(select(Alert.id).where(Alert.screening_id.like("RR-%")))).scalars().all()
        await s.execute(delete(CaseLabel).where(CaseLabel.alert_id.in_(ids)))
        await s.execute(delete(Evidence).where(Evidence.alert_id.in_(ids)))
        await s.execute(delete(Alert).where(Alert.id.in_(ids)))
        await s.execute(delete(Screening).where(Screening.id.like("RR-%")))
        await s.execute(delete(ReplayRun))
        await s.commit()


async def _finish_running() -> None:
    """Tra un test e l'altro nessuna rivalutazione resta «in corso» (una alla volta)."""
    from sqlalchemy import update

    from app.db import SessionLocal
    from app.models import ReplayRun
    async with SessionLocal() as s:
        await s.execute(update(ReplayRun).where(ReplayRun.status == "running").values(status="failed"))
        await s.commit()


async def _main() -> int:
    if not DB_URL:
        print("SKIP: TEST_DATABASE_URL non impostata (serve un PostgreSQL)")
        return 0
    import httpx

    from app.config import settings
    from app.db import init_db
    from app.main import app
    from app.routers import replay

    await init_db()
    saved = (settings.app_env, settings.internal_api_token, replay.get_client)
    settings.app_env, settings.internal_api_token = "development", TOKEN
    await _cleanup()
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        for fn in tests:
            try:
                await fn(client)
                print(f"PASS {fn.__name__}")
            except Exception as exc:  # noqa: BLE001 — anche un 500/eccezione dell'app è un FAIL
                fails += 1
                print(f"FAIL {fn.__name__}: {exc!r}"[:600])
            finally:
                await _finish_running()
    settings.app_env, settings.internal_api_token, replay.get_client = saved
    await _cleanup()
    print(f"\n{len(tests) - fails}/{len(tests)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
