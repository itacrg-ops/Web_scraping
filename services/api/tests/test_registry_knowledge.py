"""Test d'integrazione: cancellazione di alert, casi collegati nel dataset, nomi simili
(decisioni per l'Entity Resolution), conferma degli articoli nel registro, audit.
Richiedono PostgreSQL:
    TEST_DATABASE_URL=postgresql://… python services/api/tests/test_registry_knowledge.py
(senza TEST_DATABASE_URL vengono SALTATI e lo dichiarano).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

DB_URL = os.getenv("TEST_DATABASE_URL", "")
if DB_URL:
    os.environ["DATABASE_URL"] = DB_URL  # prima di importare app.* (engine creato all'import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TOKEN = "tok-registry"
TAG = uuid.uuid4().hex[:6]   # nomi unici per esecuzione: i test non si pestano i piedi
START = datetime.now(timezone.utc)


async def _screening() -> str:
    from app.db import SessionLocal
    from app.models import Screening
    sid = f"K-{uuid.uuid4().hex[:12]}"
    async with SessionLocal() as s:
        s.add(Screening(id=sid, denominazione="x", status="running"))
        await s.commit()
    return sid


async def _alert(client, subject: str, urls: list[str], tipo: str = "persona_giuridica", **kw) -> dict:
    from app.config import settings
    settings.internal_api_token = TOKEN
    payload = {"screening_id": await _screening(), "subject": subject, "tipo_soggetto": tipo,
               "ami_score": 70, "risk_level": "MEDIO", "disposition": "ESCALATION_I_LIVELLO",
               "evidence": [{"url": u, "testata": "t.it", "content_hash": f"h-{u}"} for u in urls], **kw}
    r = await client.post("/api/alerts", json=payload, headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 201, r.text
    settings.internal_api_token = ""
    return r.json()


def _label(a: dict, judgments: list[tuple[str, str]], **kw) -> dict:
    return {"evidence_labels": {e["id"]: {"pertinenza": p, "avversa": v}
                                for e, (p, v) in zip(a["evidence"], judgments)},
            "categorie_corrette": ["Corruption & Bribery"], "ruolo": "autore_indagato",
            "disposition_attesa": "ESCALATION_I_LIVELLO", "affidabile": False, **kw}


async def _audit(object_id: str) -> list:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import AuditLog
    async with SessionLocal() as s:
        return list((await s.execute(select(AuditLog).where(AuditLog.object_id == object_id))).scalars().all())


def _as(user_name: str, sub: str, roles: list[str]):
    from app.auth import User, require_user
    from app.main import app
    app.dependency_overrides[require_user] = lambda: User(name=user_name, sub=sub, roles=roles)


def _as_dev() -> None:
    from app.auth import require_user
    from app.main import app
    app.dependency_overrides.pop(require_user, None)


# --- (a) cancellazione ------------------------------------------------------------
async def test_delete_duplicates_with_labels_and_audit(client) -> None:
    a1 = await _alert(client, f"Delta {TAG} S.r.l.", ["https://d.it/1"])
    a2 = await _alert(client, f"Delta {TAG} SRL", ["https://d.it/1"], svi_status="published",
                      svi_alert_id="SVI-123")
    assert (await client.put(f"/api/alerts/{a1['id']}/label",
                             json=_label(a1, [("si", "si")], affidabile=True))).status_code == 200
    _as("Revisore", "rev-x", roles=[])                       # senza ruolo: vietato
    try:
        r = await client.post("/api/alerts/delete", json={"ids": [a1["id"]], "motivo": "duplicato"})
        assert r.status_code == 403, r.text
    finally:
        _as_dev()
    r = await client.post("/api/alerts/delete", json={"ids": [a1["id"], a2["id"]], "motivo": "duplicato",
                                                      "nota": "doppio screening"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["eliminati"] == 2 and body["etichette_eliminate"] == 1
    assert body["in_svi"] == [{"id": a2["id"], "svi_alert_id": "SVI-123"}]   # da chiudere in SAS VI
    assert (await client.get(f"/api/alerts/{a1['id']}")).status_code == 404
    assert (await client.get(f"/api/alerts/{a1['id']}/label")).status_code == 404
    log = await _audit(a1["id"])
    assert len(log) == 1 and log[0].action == "alert.delete"
    assert log[0].details["motivo"] == "duplicato" and log[0].details["affidabili"] == 1
    bad = await client.post("/api/alerts/delete", json={"ids": [a2["id"]], "motivo": "boh"})
    assert bad.status_code == 422


# --- (b) casi collegati durante l'etichettatura --------------------------------------
async def test_related_cases_and_prior_judgments(client) -> None:
    subj = f"Epsilon {TAG} Costruzioni"
    old = await _alert(client, f"{subj} S.p.A.", ["https://e.it/1", "https://e.it/2"])
    new = await _alert(client, subj.upper(), ["https://e.it/2", "https://e.it/3"])
    other = await _alert(client, f"Zeta {TAG} S.r.l.", ["https://e.it/2"])
    await client.put(f"/api/alerts/{old['id']}/label",
                     json=_label(old, [("si", "si"), ("omonimo", "no")], affidabile=True))
    _as("Altra", "rev-2", roles=[])                         # giudizio di un altro revisore
    try:
        await client.put(f"/api/alerts/{old['id']}/label", json=_label(old, [("si", "si"), ("si", "si")]))
    finally:
        _as_dev()
    r = await client.get(f"/api/alerts/{new['id']}/related")
    assert r.status_code == 200, r.text
    rel = r.json()
    assert [c["id"] for c in rel["stesso_soggetto"]] == [old["id"]]          # non "Zeta"
    case = rel["stesso_soggetto"][0]
    assert case["etichette"] == 2 and case["affidabili"] == 1 and case["mia"] == "affidabile"
    shared = new["evidence"][0]["id"]                                         # https://e.it/2
    prior = rel["giudizi_precedenti"][shared]
    assert len(prior) == 1 and prior[0]["pertinenza"] == "omonimo"            # solo il MIO giudizio
    assert new["evidence"][1]["id"] not in rel["giudizi_precedenti"]
    assert (await client.get(f"/api/alerts/{other['id']}/related")).json()["stesso_soggetto"] == []


# --- (c) nomi simili -------------------------------------------------------------
async def test_similar_names_and_decisions(client) -> None:
    surname = f"Bertolla{TAG}"   # nome proprio del test: gli altri test registrano "Stroppa…"
    subj = (await client.post("/api/subjects", json={
        "tipo_soggetto": "persona_fisica", "cognome": surname, "nome": "Andrea"})).json()
    q = {"tipo_soggetto": "persona_fisica", "cognome": surname[:6] + surname[7:], "nome": "Andrea"}  # "Bertola…"
    sim = (await client.get("/api/subjects/similar", params=q)).json()
    hit = next(c for c in sim["simili"] if c["subject_id"] == subj["id"])
    assert hit["fonte"] == "registro" and hit["score"] >= 0.9 and sim["registro_esatto"] is None
    typo = f"{q['cognome']} Andrea"
    # «è un altro soggetto» → non viene più proposto
    r = await client.post(f"/api/subjects/{subj['id']}/names", json={"name": typo, "decision": "diverso"})
    assert r.status_code == 200 and r.json()["distinti"] == [typo]
    sim = (await client.get("/api/subjects/similar", params=q)).json()
    assert all(c["subject_id"] != subj["id"] for c in sim["simili"])
    # ripensamento: «è lo stesso» → riconosciuto come quel soggetto
    r = await client.post(f"/api/subjects/{subj['id']}/names", json={"name": typo, "decision": "stesso"})
    assert r.json()["alias"] == [typo] and r.json()["distinti"] == []
    sim = (await client.get("/api/subjects/similar", params=q)).json()
    assert sim["registro_esatto"]["subject_id"] == subj["id"]
    # l'Entity Resolution riceve varianti e soggetti distinti
    reg = (await client.get("/api/subjects/registry")).json()["subjects"]
    assert next(s for s in reg if s["id"] == subj["id"])["alias"] == [typo]
    assert (await client.post(f"/api/subjects/{subj['id']}/names",
                              json={"name": f"Andrea {surname}", "decision": "stesso"})).status_code == 422
    log = await _audit(subj["id"])
    assert [x.action for x in log].count("subject.name_stesso") == 1


async def test_similar_includes_screened_names_and_duplicates(client) -> None:
    name = f"Omega{TAG} Servizi Ambientali"
    await _alert(client, name, ["https://o.it/1"])
    await _alert(client, name + " S.r.l.", ["https://o.it/2"])
    sim = (await client.get("/api/subjects/similar", params={"denominazione": name})).json()
    assert sim["alert_esistenti"] == 2 and sim["simili"] == []               # stesso nome: duplicato
    near = (await client.get("/api/subjects/similar", params={"denominazione": f"Omeg{TAG} Servizi Ambientali"})).json()
    cand = next(c for c in near["simili"] if c["fonte"] == "screening")
    assert cand["alert"] == 2 and cand["subject_id"] is None


async def test_rename_keeps_old_name_as_variant(client) -> None:
    subj = (await client.post("/api/subjects", json={"denominazione": f"Sigma{TAG} Impianti srl"})).json()
    r = await client.patch(f"/api/subjects/{subj['id']}", json={"denominazione": f"Sigma{TAG} Impianti Nord srl"})
    assert r.status_code == 200 and r.json()["alias"] == [f"Sigma{TAG} Impianti srl"]
    assert any(x.action == "subject.rename" for x in await _audit(subj["id"]))


# --- (d) conferma nel registro ----------------------------------------------------
async def test_confirm_articles_into_registry(client) -> None:
    typo, right = f"Strop{TAG} Andrea", f"Stroppa{TAG} Andrea"
    a = await _alert(client, typo, ["https://s.it/1", "https://s.it/2"], tipo="persona_fisica")
    url = f"/api/alerts/{a['id']}/confirm"
    new = {"nuovo": {"tipo_soggetto": "persona_fisica", "denominazione": right}}
    assert (await client.post(url, json=new)).status_code == 409                       # etichetta mancante
    await client.put(f"/api/alerts/{a['id']}/label", json=_label(a, [("incerto", "no"), ("incerto", "si")]))
    assert (await client.post(url, json=new)).status_code == 422                       # niente di certo
    await client.put(f"/api/alerts/{a['id']}/label", json=_label(a, [("si", "si"), ("incerto", "no")]))
    assert (await client.post(url, json={})).status_code == 422                        # destinazione?
    r = await client.post(url, json=new)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["confermati"] == 1 and out["saltati"] == 1 and out["alias_aggiunto"] == typo
    sid = out["subject"]["id"]
    assert out["subject"]["denominazione"] == right and out["subject"]["articoli_confermati"] == 1
    arts = (await client.get(f"/api/subjects/{sid}/articles")).json()
    assert [(x["url"], x["pertinenza"], x["avversa"]) for x in arts] == [("https://s.it/1", "si", "si")]
    assert arts[0]["categorie"] == ["Corruption & Bribery"] and arts[0]["alert_id"] == a["id"]
    # rifare la conferma aggiorna, non duplica; un nuovo soggetto con lo stesso nome è rifiutato
    await client.put(f"/api/alerts/{a['id']}/label", json=_label(a, [("si", "no"), ("omonimo", "no")]))
    r2 = (await client.post(url, json={"subject_id": sid})).json()
    assert r2["confermati"] == 2 and r2["alias_aggiunto"] is None
    arts = {x["url"]: x for x in (await client.get(f"/api/subjects/{sid}/articles")).json()}
    assert arts["https://s.it/1"]["avversa"] == "no" and arts["https://s.it/2"]["pertinenza"] == "omonimo"
    assert (await client.post(url, json=new)).status_code == 409
    # la scheda del caso vede il soggetto (tramite la variante) e gli articoli confermati
    rel = (await client.get(f"/api/alerts/{a['id']}/related")).json()["registro"]
    assert rel["subject_id"] == sid and rel["come"] == "alias"
    # l'alert col refuso è ormai dello stesso soggetto: non va riproposto come «già screenato»
    sim = (await client.get("/api/subjects/similar", params={"tipo_soggetto": "persona_fisica",
                                                           "cognome": f"Stropo{TAG}", "nome": "Andrea"})).json()
    assert all(c["fonte"] == "registro" for c in sim["simili"]), sim
    assert next(c for c in sim["simili"] if c["subject_id"] == sid)["alert"] == 1
    assert rel["articoli"][a["evidence"][1]["id"]]["pertinenza"] == "omonimo"
    assert {x.action for x in await _audit(sid)} >= {"subject.create", "subject.confirm_articles"}


# --- soggetto già inserito, PEP e ruoli dagli articoli ------------------------------
async def test_already_registered_pep_and_roles(client) -> None:
    name = f"Verdi{TAG} Anna"
    first = await client.post("/api/subjects", json={"tipo_soggetto": "persona_fisica", "denominazione": name,
                                                     "cf_piva": "VRDNNA85M41H501K"})
    assert first.status_code == 201, first.text
    sid = first.json()["id"]
    for dup in ({"denominazione": name}, {"denominazione": f"Anna Verdi{TAG}"},            # stesso nome
                {"denominazione": "Qualcun Altro", "cf_piva": "vrdnna85m41h501k"}):         # stesso CF
        r = await client.post("/api/subjects", json={"tipo_soggetto": "persona_fisica", **dup})
        assert r.status_code == 409 and "Soggetto già inserito nel registro" in r.text, r.text
    homonym = await client.post("/api/subjects", json={"tipo_soggetto": "persona_fisica", "denominazione": name,
                                                       "cf_piva": "VRDNNA70A41F205X"})
    assert homonym.status_code == 201, homonym.text                                         # omonimo: CF diverso
    hid = homonym.json()["id"]

    # /similar con il CF: «già inserito» con la stessa regola; lo stesso nome con altro CF è un omonimo
    async def similar(denominazione, cf):
        r = await client.get("/api/subjects/similar", params={"tipo_soggetto": "persona_fisica",
                                                               "denominazione": denominazione, "cf_piva": cf})
        body = r.json()
        return (body["registro_esatto"] or {}).get("subject_id"), {c["subject_id"] for c in body["simili"]
                                                                      if c["score"] == 1.0}
    assert await similar("Qualcun Altro", "vrdnna85m41h501k") == (sid, set())
    assert await similar(name, "VRDNNA70A41F205X") == (hid, {sid})
    assert await similar(name, "VRDNNA90A41F205Y") == (None, {sid, hid})

    # anche la data di nascita distingue gli omonimi (registro senza CF)
    born = f"Gialli{TAG} Rita"
    r = await client.post("/api/subjects", json={"tipo_soggetto": "persona_fisica", "denominazione": born,
                                                 "data_nascita": "1970-01-01"})
    assert r.status_code == 201, r.text
    for dob, status in (("1970-01-01", 409), (None, 409), ("1981-02-02", 201)):
        r = await client.post("/api/subjects", json={"tipo_soggetto": "persona_fisica", "denominazione": born,
                                                     **({"data_nascita": dob} if dob else {})})
        assert r.status_code == status, (dob, r.text)
    # con due omonimi a registro: già inserito solo se non distinto da nessuno dei due
    r = await client.post("/api/subjects", json={"tipo_soggetto": "persona_fisica", "denominazione": born,
                                                 "data_nascita": "1981-02-02"})
    assert r.status_code == 409, r.text

    # alert di una persona con ruoli e PEP (dal worker) → scheda ed export
    a = await _alert(client, name, ["https://p.it/1"], tipo="persona_fisica", cf_piva="VRDNNA85M41H501K",
                     roles=[{"ruolo": "sindaco di Latina", "tipo": "sindaco", "categoria": "pep",
                             "pep": "verifica", "ex": False, "articoli": 1}], pep=True)
    got = (await client.get(f"/api/alerts/{a['id']}")).json()
    assert got["pep"] is True and got["roles"][0]["ruolo"] == "sindaco di Latina"

    # conferma nel registro: soggetto già inserito, ruoli e PEP confermati
    await client.put(f"/api/alerts/{a['id']}/label", json=_label(a, [("si", "si")]))
    r = await client.post(f"/api/alerts/{a['id']}/confirm", json={
        "subject_id": sid, "cariche": ["sindaco di Latina", "Sindaco di  Latina", "imprenditrice"], "pep": True})
    out = r.json()
    assert r.status_code == 200 and out["nuovo_soggetto"] is False, r.text
    assert out["subject"]["pep"] is True and out["subject"]["cariche"] == ["sindaco di Latina", "imprenditrice"]
    new = await client.post(f"/api/alerts/{a['id']}/confirm", json={
        "nuovo": {"tipo_soggetto": "persona_fisica", "denominazione": name, "cf_piva": "VRDNNA85M41H501K"}})
    assert new.status_code == 409 and "Soggetto già inserito" in new.text
    # modificabili dalla pagina Soggetti
    r = await client.patch(f"/api/subjects/{sid}", json={"pep": False, "cariche": ["assessora"]})
    assert r.json()["pep"] is False and r.json()["cariche"] == ["assessora"]


async def test_csv_import_pep_roles_without_duplicates(client) -> None:
    csv = ("tipo_soggetto,denominazione,nome,cognome,cf_piva,pep,cariche\n"
           f"persona_fisica,,Luca,Neri{TAG},,si,sindaco di Latina;AD di Acme\n"
           f"persona_fisica,,Luca,Neri{TAG},,,dirigente\n")      # stesso nome senza CF: aggiorna
    r = (await client.post("/api/subjects/import", json={"csv": csv})).json()
    assert (r["created"], r["updated"], r["errors"]) == (1, 1, []), r
    subj = next(s for s in (await client.get("/api/subjects")).json() if s["denominazione"] == f"Neri{TAG} Luca")
    assert subj["pep"] is True and subj["cariche"] == ["sindaco di Latina", "AD di Acme", "dirigente"]

    # una riga scritta con una variante confermata aggiorna il soggetto senza rinominarlo
    await client.post(f"/api/subjects/{subj['id']}/names", json={"name": f"Nerri{TAG} Luca", "decision": "stesso"})
    csv = "tipo_soggetto,denominazione,nome,cognome,cf_piva,ruolo\n" + f"persona_fisica,,Luca,Nerri{TAG},,RUP\n"
    r = (await client.post("/api/subjects/import", json={"csv": csv})).json()
    assert (r["created"], r["updated"]) == (0, 1), r
    subj = next(s for s in (await client.get("/api/subjects")).json() if s["id"] == subj["id"])
    assert subj["denominazione"] == f"Neri{TAG} Luca" and subj["ruolo"] == "RUP", subj

    # celle vuote: non cancellano i dati; il CF aggiunto vale per le righe successive
    csv = ("tipo_soggetto,denominazione,nome,cognome,cf_piva,ruolo,cup\n"
           f"persona_fisica,,Luca,Neri{TAG},NRELCU80A01H501Z,,\n"
           f"persona_fisica,,Luchino,Neri{TAG},NRELCU80A01H501Z,,E51B21000000001\n")
    r = (await client.post("/api/subjects/import", json={"csv": csv})).json()
    assert (r["created"], r["updated"]) == (0, 2), r
    subj = next(s for s in (await client.get("/api/subjects")).json() if s["id"] == subj["id"])
    assert subj["ruolo"] == "RUP" and subj["cf_piva"] == "NRELCU80A01H501Z" and subj["cup"] == ["E51B21000000001"]


async def _cleanup() -> None:
    from sqlalchemy import delete, select

    from app.db import SessionLocal
    from app.models import Alert, AuditLog, CaseLabel, Evidence, Screening, Subject
    async with SessionLocal() as s:
        ids = (await s.execute(select(Alert.id).where(Alert.screening_id.like("K-%")))).scalars().all()
        await s.execute(delete(CaseLabel).where(CaseLabel.alert_id.in_(ids)))
        await s.execute(delete(Evidence).where(Evidence.alert_id.in_(ids)))
        await s.execute(delete(Alert).where(Alert.id.in_(ids)))
        await s.execute(delete(Screening).where(Screening.id.like("K-%")))
        subj = (await s.execute(select(Subject.id).where(Subject.denominazione.contains(TAG)))).scalars().all()
        await s.execute(delete(Subject).where(Subject.id.in_(subj)))
        await s.execute(delete(AuditLog).where(AuditLog.ts >= START))
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
                print(f"FAIL {fn.__name__}: {exc!r}"[:600])
            finally:
                settings.app_env, settings.internal_api_token = saved
                _as_dev()
    await _cleanup()
    print(f"\n{len(tests) - fails}/{len(tests)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
