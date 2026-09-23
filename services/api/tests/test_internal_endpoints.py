"""Test d'integrazione degli endpoint interni dell'API (richiedono PostgreSQL).

Coprono: protezione di `/api/subjects/registry` col token di servizio,
persistenza **idempotente** dell'alert per screening (anche con richieste
concorrenti), esito di pubblicazione SVI, screening marcato `failed`.

    TEST_DATABASE_URL=postgresql://ams:ams@localhost:5432/ams \
        python services/api/tests/test_internal_endpoints.py

Senza TEST_DATABASE_URL i test vengono SALTATI (lo dichiarano in output).
Applicano le migrazioni (upgrade head) e usano id univoci, poi ripuliscono.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

DB_URL = os.getenv("TEST_DATABASE_URL", "")
if DB_URL:
    os.environ["DATABASE_URL"] = DB_URL  # prima di importare app.* (engine creato all'import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TOKEN = "tok-test-123"


def _alert_payload(screening_id: str) -> dict:
    return {"screening_id": screening_id, "subject": "ACME Test", "ami_score": 70,
            "risk_level": "MEDIO", "disposition": "ESCALATION_I_LIVELLO",
            "evidence": [{"url": "https://news.example/a", "content_hash": "h1"}]}


async def _new_screening(status: str = "running") -> str:
    from app.db import SessionLocal
    from app.models import Screening

    sid = f"T-{uuid.uuid4().hex[:12]}"
    async with SessionLocal() as s:
        s.add(Screening(id=sid, denominazione="ACME Test", status=status))
        await s.commit()
    return sid


async def test_registry_requires_internal_token(client, settings) -> None:
    settings.app_env, settings.internal_api_token = "production", TOKEN
    assert (await client.get("/api/subjects/registry")).status_code == 401
    r = await client.get("/api/subjects/registry", headers={"X-Internal-Token": "sbagliato"})
    assert r.status_code == 401
    r = await client.get("/api/subjects/registry", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200 and "subjects" in r.json()
    # token non configurato: chiuso fuori da development (fail-closed)…
    settings.internal_api_token = ""
    assert (await client.get("/api/subjects/registry")).status_code == 503
    # …aperto solo in development (comportamento locale invariato)
    settings.app_env = "development"
    assert (await client.get("/api/subjects/registry")).status_code == 200


async def test_alert_post_is_idempotent_per_screening(client, settings) -> None:
    settings.app_env, settings.internal_api_token = "production", TOKEN
    h = {"X-Internal-Token": TOKEN}
    sid = await _new_screening()
    r1 = await client.post("/api/alerts", json=_alert_payload(sid), headers=h)
    r2 = await client.post("/api/alerts", json=_alert_payload(sid), headers=h)  # retry del worker
    assert r1.status_code == 201 and r2.status_code == 200, (r1.status_code, r2.status_code)
    assert r1.json()["id"] == r2.json()["id"]
    assert r1.json()["svi_status"] == "pending" and len(r2.json()["evidence"]) == 1
    s = (await client.get(f"/api/screening/{sid}")).json()
    assert s["status"] == "completed" and s["alert_id"] == r1.json()["id"]
    # senza token la scrittura è rifiutata
    assert (await client.post("/api/alerts", json=_alert_payload(sid))).status_code == 401


async def test_insert_race_returns_existing_alert(client, settings) -> None:
    """Corsa tra due richieste per lo stesso screening: la seconda supera il
    pre-controllo prima che la prima abbia salvato → l'INSERT urta il vincolo unique
    e deve restituire l'alert esistente (non un 500, non un duplicato). La corsa è
    forzata in modo deterministico: il pre-controllo "non vede" l'alert esistente."""
    settings.app_env, settings.internal_api_token = "production", TOKEN
    h = {"X-Internal-Token": TOKEN}
    sid = await _new_screening()
    first = (await client.post("/api/alerts", json=_alert_payload(sid), headers=h)).json()

    from app.routers import alerts as alerts_router
    real_load, calls = alerts_router._load, {"n": 0}

    async def racing_load(session, *where):
        calls["n"] += 1
        return None if calls["n"] == 1 else await real_load(session, *where)

    alerts_router._load = racing_load
    try:
        r = await client.post("/api/alerts", json=_alert_payload(sid), headers=h)
    finally:
        alerts_router._load = real_load
    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.json()["id"] == first["id"]

    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Alert
    async with SessionLocal() as s:
        n = (await s.execute(select(func.count()).select_from(Alert).where(Alert.screening_id == sid))).scalar()
    assert n == 1, n


async def test_svi_outcome_is_recorded(client, settings) -> None:
    settings.app_env, settings.internal_api_token = "production", TOKEN
    h = {"X-Internal-Token": TOKEN}
    aid = (await client.post("/api/alerts", json=_alert_payload(await _new_screening()), headers=h)).json()["id"]
    r = await client.patch(f"/api/alerts/{aid}/svi", headers=h,
                           json={"svi_status": "failed", "svi_error": "SVI non disponibile (HTTP 502)"})
    assert r.status_code == 200 and r.json()["svi_status"] == "failed"
    assert r.json()["svi_error"].startswith("SVI non disponibile")
    r = await client.patch(f"/api/alerts/{aid}/svi", headers=h,
                           json={"svi_status": "published", "svi_alert_id": "svi-123"})
    assert r.json()["svi_status"] == "published" and r.json()["svi_alert_id"] == "svi-123"
    assert r.json()["svi_error"] is None
    assert (await client.patch(f"/api/alerts/{aid}/svi", json={"svi_status": "failed"})).status_code == 401
    bad = await client.patch(f"/api/alerts/{aid}/svi", headers=h, json={"svi_status": "boh"})
    assert bad.status_code == 422


async def test_screening_marked_failed_only_from_running(client, settings) -> None:
    settings.app_env, settings.internal_api_token = "production", TOKEN
    h = {"X-Internal-Token": TOKEN}
    sid = await _new_screening()
    r = await client.post(f"/api/screening/{sid}/failed", headers=h, json={"error": "ActivityError: search"})
    assert r.status_code == 200 and r.json()["status"] == "failed" and "search" in r.json()["error"]
    done = await _new_screening(status="completed")
    r = await client.post(f"/api/screening/{done}/failed", headers=h, json={"error": "tardivo"})
    assert r.json()["status"] == "completed"                 # non retrocesso
    assert (await client.post(f"/api/screening/{sid}/failed", json={"error": "x"})).status_code == 401


async def _cleanup() -> None:
    from sqlalchemy import delete, select

    from app.db import SessionLocal
    from app.models import Alert, Evidence, Screening
    async with SessionLocal() as s:
        ids = (await s.execute(select(Alert.id).where(Alert.screening_id.like("T-%")))).scalars().all()
        await s.execute(delete(Evidence).where(Evidence.alert_id.in_(ids)))
        await s.execute(delete(Alert).where(Alert.id.in_(ids)))
        await s.execute(delete(Screening).where(Screening.id.like("T-%")))
        await s.commit()


async def _main() -> int:
    if not DB_URL:
        print("SKIP: TEST_DATABASE_URL non impostata (serve un PostgreSQL)")
        return 0
    import httpx

    from app.config import settings
    from app.db import init_db
    from app.main import app

    await init_db()
    saved = (settings.app_env, settings.internal_api_token)
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        for fn in tests:
            try:
                await fn(client, settings)
                print(f"PASS {fn.__name__}")
            except Exception as exc:  # noqa: BLE001 — anche un 500/eccezione dell'app è un FAIL
                fails += 1
                print(f"FAIL {fn.__name__}: {exc!r}"[:400])
            finally:
                settings.app_env, settings.internal_api_token = saved
    await _cleanup()
    print(f"\n{len(tests) - fails}/{len(tests)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
