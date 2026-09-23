"""Test d'integrazione delle etichette dei casi (dataset di valutazione). Richiedono
PostgreSQL: TEST_DATABASE_URL=postgresql://… python services/api/tests/test_labels.py
(senza TEST_DATABASE_URL vengono SALTATI e lo dichiarano).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

DB_URL = os.getenv("TEST_DATABASE_URL", "")
if DB_URL:
    os.environ["DATABASE_URL"] = DB_URL  # prima di importare app.* (engine creato all'import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TOKEN = "tok-labels"


async def _alert_with_evidence(client, disposition: str = "ESCALATION_I_LIVELLO") -> dict:
    """Crea (via endpoint interno, come il worker) un alert con 2 evidenze e predizioni."""
    from app.config import settings
    settings.internal_api_token = TOKEN
    sid = await _screening()
    payload = {
        "screening_id": sid, "subject": "ACME Costruzioni S.r.l.", "cf_piva": "00743110157",
        "ami_score": 78, "risk_level": "ALTO", "disposition": disposition,
        "fatf_categories": ["Money Laundering"],
        "classification": {"method": "euristica_keyword", "severity": None},
        "evidence": [
            {"url": "https://a.it/1", "testata": "a.it", "content_hash": "h1", "mentioned": True,
             "mention_match": ["denominazione"]},
            {"url": "https://b.it/2", "content_hash": "h2", "mentioned": False, "mention_match": []},
        ],
    }
    r = await client.post("/api/alerts", json=payload, headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 201, r.text
    return r.json()


async def _screening() -> str:
    from app.db import SessionLocal
    from app.models import Screening
    sid = f"L-{uuid.uuid4().hex[:12]}"
    async with SessionLocal() as s:
        s.add(Screening(id=sid, denominazione="ACME", status="running"))
        await s.commit()
    return sid


def _complete(a: dict, **kw) -> dict:
    e1, e2 = (e["id"] for e in a["evidence"])
    return {"evidence_labels": {e1: {"pertinenza": "si", "avversa": "no"},
                                e2: {"pertinenza": "omonimo", "avversa": "no"}},
            "categorie_corrette": [], "ruolo": "menzionato", "disposition_attesa": "AUTO_CHIUSO",
            "affidabile": True, "note": "impianto di riciclo: falso positivo", **kw}


async def test_alert_exposes_predictions(client) -> None:
    a = await _alert_with_evidence(client)
    assert a["classification"]["method"] == "euristica_keyword"
    assert [e["mentioned"] for e in a["evidence"]] == [True, False]
    assert a["evidence"][0]["id"] and a["evidence"][0]["mention_match"] == ["denominazione"]


async def test_label_roundtrip_and_update(client) -> None:
    a = await _alert_with_evidence(client)
    url = f"/api/alerts/{a['id']}/label"
    assert (await client.get(url)).json() is None                 # non ancora etichettato
    r1 = await client.put(url, json=_complete(a))
    assert r1.status_code == 200, r1.text
    r2 = await client.put(url, json=_complete(a, note="rivisto"))  # aggiornamento, stessa riga
    assert r2.json()["id"] == r1.json()["id"] and r2.json()["note"] == "rivisto"
    got = (await client.get(url)).json()
    assert got["affidabile"] is True and got["evidence_labels"][a["evidence"][1]["id"]]["pertinenza"] == "omonimo"
    assert any(x["alert_id"] == a["id"] for x in (await client.get("/api/labels")).json())
    assert (await client.delete(url)).status_code == 204
    assert (await client.get(url)).json() is None


async def test_validation(client) -> None:
    a = await _alert_with_evidence(client)
    url = f"/api/alerts/{a['id']}/label"
    bad_ev = await client.put(url, json={"evidence_labels": {"non-esiste": {"pertinenza": "si"}}})
    assert bad_ev.status_code == 422 and "non appartenenti" in bad_ev.text
    bad_cat = await client.put(url, json={"categorie_corrette": ["Riciclo"]})
    assert bad_cat.status_code == 422
    e1 = a["evidence"][0]["id"]
    incompleto = {"evidence_labels": {e1: {"pertinenza": "incerto", "avversa": "no"}},
                  "disposition_attesa": "AUTO_CHIUSO", "affidabile": True}
    r = await client.put(url, json=incompleto)
    assert r.status_code == 422, r.text
    # cosa manca, in termini del revisore: numero e testata dell'articolo, domanda — non gli id
    detail = r.json()["detail"]
    assert "ruolo del soggetto" in detail and "esito corretto" not in detail, detail
    assert "articolo 1 (a.it): riguarda il soggetto? «Incerto»" in detail, detail    # «Incerto» non basta
    assert "articolo 2 (fonte): riguarda il soggetto?, notizia avversa?" in detail, detail
    assert not any(e["id"] in detail for e in a["evidence"]), detail
    # lo stesso giudizio, NON marcato affidabile, si salva (bozza)
    assert (await client.put(url, json={**incompleto, "affidabile": False})).status_code == 200
    assert (await client.get("/api/alerts/non-esiste/label")).status_code == 404


async def test_one_label_per_reviewer(client) -> None:
    from app.auth import User, require_user
    from app.main import app
    a = await _alert_with_evidence(client)
    url = f"/api/alerts/{a['id']}/label"
    await client.put(url, json=_complete(a))
    app.dependency_overrides[require_user] = lambda: User(name="Seconda Revisora", sub="rev-2",
                                                          roles=[])
    try:
        r = await client.put(url, json=_complete(a, disposition_attesa="ESCALATION_I_LIVELLO"))
        assert r.status_code == 200 and r.json()["reviewer"] == "rev-2"
        stats = (await client.get("/api/labels/stats")).json()
        assert stats["revisori"] >= 2
        # l'export richiede un ruolo autorizzato: questa revisora non ce l'ha
        assert (await client.get("/api/labels/export")).status_code == 403
    finally:
        app.dependency_overrides.pop(require_user, None)


async def test_stats_show_selection_bias(client) -> None:
    before = (await client.get("/api/labels/stats")).json()
    a = await _alert_with_evidence(client, disposition="AUTO_CHIUSO")
    await client.put(f"/api/alerts/{a['id']}/label", json=_complete(a))
    after = (await client.get("/api/labels/stats")).json()
    assert after["etichettati"] == before["etichettati"] + 1
    assert after["per_disposition"].get("AUTO_CHIUSO", 0) == before["per_disposition"].get("AUTO_CHIUSO", 0) + 1
    assert after["affidabili_per_disposition"].get("AUTO_CHIUSO", 0) >= 1


async def test_export_ndjson(client) -> None:
    a = await _alert_with_evidence(client)
    await client.put(f"/api/alerts/{a['id']}/label", json=_complete(a))
    r = await client.get("/api/labels/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in r.headers["content-disposition"]
    rows = [json.loads(line) for line in r.text.splitlines()]
    mine = next(x for x in rows if x["alert"]["id"] == a["id"])
    assert mine["schema"] == "ams-case-label/1" and mine["label"]["affidabile"] is True
    assert "cf_piva" not in mine["alert"]                      # minimizzazione
    ev = {e["url"]: e for e in mine["evidence"]}
    assert ev["https://a.it/1"]["mentioned"] is True and ev["https://a.it/1"]["label"]["pertinenza"] == "si"
    assert ev["https://b.it/2"]["label"]["pertinenza"] == "omonimo"
    assert all(x["label"]["affidabile"] for x in rows)          # default: solo affidabili


async def test_replay_input_is_internal(client) -> None:
    """La rivalutazione (worker) riceve anche CF/P.IVA e snapshot; l'export no."""
    from app.config import settings
    a = await _alert_with_evidence(client)
    await client.put(f"/api/alerts/{a['id']}/label", json=_complete(a))
    settings.internal_api_token = TOKEN
    assert (await client.get("/api/labels/replay")).status_code == 401
    r = await client.get("/api/labels/replay", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200, r.text
    rec = next(x for x in r.json()["records"] if x["alert"]["id"] == a["id"])
    assert rec["alert"]["cf_piva"] == "00743110157" and "entity_resolution" in rec["alert"]
    assert all("raw_key" in e and "bucket" in e for e in rec["evidence"])
    exported = [json.loads(line) for line in (await client.get("/api/labels/export")).text.splitlines()]
    mine = next(x for x in exported if x["alert"]["id"] == a["id"])
    assert "cf_piva" not in mine["alert"] and all("raw_key" not in e for e in mine["evidence"])


async def _cleanup() -> None:
    from sqlalchemy import delete, select

    from app.db import SessionLocal
    from app.models import Alert, CaseLabel, Evidence, Screening
    async with SessionLocal() as s:
        ids = (await s.execute(select(Alert.id).where(Alert.screening_id.like("L-%")))).scalars().all()
        await s.execute(delete(CaseLabel).where(CaseLabel.alert_id.in_(ids)))
        await s.execute(delete(Evidence).where(Evidence.alert_id.in_(ids)))
        await s.execute(delete(Alert).where(Alert.id.in_(ids)))
        await s.execute(delete(Screening).where(Screening.id.like("L-%")))
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
                await fn(client)
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
