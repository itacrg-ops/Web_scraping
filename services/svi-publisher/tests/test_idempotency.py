"""Test dell'idempotenza (mock): ripubblicare lo stesso screening non crea
duplicati e restituisce lo stesso id.

    pytest services/svi-publisher/tests/test_idempotency.py
    python  services/svi-publisher/tests/test_idempotency.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app import mapping, svi_client  # noqa: E402
from app.config import settings  # noqa: E402

ALERT = {"subject": "ACME S.r.l.", "cf_piva": "00743110157", "cup": ["E51B21000000001"],
         "ami_score": 82, "risk_level": "ALTO", "fatf_categories": ["Money Laundering"],
         "drivers": ["AMI = 82"], "disposition": "ESCALATION_I_LIVELLO",
         "screening_id": "SCR-DEDUP-1", "evidence": []}


class _FakeResp:
    """Risposta httpx finta per il ramo live (nessuna rete)."""
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"
        self.text = str(payload)
        self.request = httpx.Request("POST", "https://viya.example/svi-alert/alertingEvents")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(str(self.status_code), request=self.request, response=self)


class _FakeClient:
    """Sostituto di httpx.AsyncClient. `spec` è una risposta unica (per ogni POST/GET)
    oppure un dict {sottostringa-url: risposta} per instradare chiamate diverse
    (es. /svi-datahub/documents vs /svi-alert/alertingEvents)."""
    def __init__(self, spec):
        self._spec = spec

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _pick(self, url: str) -> _FakeResp:
        if isinstance(self._spec, dict):
            for frag, resp in self._spec.items():
                if frag in url:
                    return resp
            raise AssertionError(f"nessuna risposta finta per {url}")
        return self._spec

    async def post(self, url, *a, **k):
        return self._pick(url)

    async def get(self, url, *a, **k):
        return self._pick(url)


def _run_live(spec, alert: dict, load_entity: bool = False, dedup_on_1008: bool = False) -> dict:
    """Esegue publish_alert nel ramo live con client/auth finti, poi ripristina."""
    settings.svi_mode = "live"
    settings.svi_load_entity = load_entity
    settings.svi_dedup_on_1008 = dedup_on_1008
    settings.svi_queue = "queue_test"
    settings.svi_alert_type_code = "strategy_default"
    svi_client.reset_idempotency()
    orig_client, orig_bearer = svi_client.httpx.AsyncClient, svi_client.auth.bearer

    async def _fake_bearer(_client):
        return "tok"

    svi_client.httpx.AsyncClient = lambda *a, **k: _FakeClient(spec)
    svi_client.auth.bearer = _fake_bearer
    try:
        return asyncio.run(svi_client.publish_alert(alert))
    finally:
        svi_client.httpx.AsyncClient = orig_client
        svi_client.auth.bearer = orig_bearer
        settings.svi_mode = "mock"
        settings.svi_load_entity = False
        settings.svi_dedup_on_1008 = False


def test_mock_publish_is_idempotent_per_screening():
    settings.svi_mode = "mock"
    svi_client.reset_idempotency()
    r1 = asyncio.run(svi_client.publish_alert(dict(ALERT)))
    r2 = asyncio.run(svi_client.publish_alert(dict(ALERT)))
    assert r1["deduplicated"] is False
    assert r2["deduplicated"] is True                 # seconda volta = dedup
    assert r1["svi_alert_id"] == r2["svi_alert_id"]   # stesso id
    assert r1["svi_alert_id"].startswith("svi-mock-")


def test_different_screening_yields_different_id():
    settings.svi_mode = "mock"
    svi_client.reset_idempotency()
    r1 = asyncio.run(svi_client.publish_alert({**ALERT, "screening_id": "A"}))
    r2 = asyncio.run(svi_client.publish_alert({**ALERT, "screening_id": "B"}))
    assert r1["svi_alert_id"] != r2["svi_alert_id"]
    assert r1["deduplicated"] is False and r2["deduplicated"] is False


def test_live_1008_raises_by_default():
    """errorCode 1008 è ambiguo (config errata vs duplicato): di default NON va mascherato
    da successo → deve sollevare, così l'errore reale (alert NON creato) è visibile."""
    a = {**ALERT, "screening_id": "ERR-1008"}
    try:
        _run_live(_FakeResp(500, {"errorCode": 1008, "message": "A data error occurred"}), a)
    except httpx.HTTPStatusError:
        return
    raise AssertionError("un 1008 di default deve sollevare, non ritornare deduplicated")


def test_live_1008_dedup_only_when_optin():
    """Con SVI_DEDUP_ON_1008=true il 1008 è trattato come duplicato idempotente."""
    a = {**ALERT, "screening_id": "DUP-1008"}
    r = _run_live(_FakeResp(500, {"errorCode": 1008, "message": "A data error occurred"}), a, dedup_on_1008=True)
    assert r["deduplicated"] is True
    assert r["svi_alert_id"] == mapping.event_id(a)


def test_live_success_201_returns_event_id():
    """Sul 201 (creato) senza items nel body, l'id ricade sull'alertingEventId nostro."""
    a = {**ALERT, "screening_id": "OK-201"}
    r = _run_live(_FakeResp(201, {"links": [{"rel": "self", "href": "/svi-alert/alertingEvents"}]}), a)
    assert r["deduplicated"] is False
    assert r["svi_alert_id"] == mapping.event_id(a)


def test_live_entity_load_failure_does_not_block_alert():
    """SVI_LOAD_ENTITY=true: un 400 sul documento Data Hub NON deve bloccare l'alert
    (l'entità non è richiesta) → si prosegue con l'alerting event, document_id=None."""
    a = {**ALERT, "screening_id": "DOC-400"}
    spec = {
        "/svi-datahub/documents": _FakeResp(400, {"errorCode": 5104, "message": "identificativo"}),
        "/svi-alert/alertingEvents": _FakeResp(201, {"links": []}),
    }
    r = _run_live(spec, a, load_entity=True)
    assert r["deduplicated"] is False
    assert r["svi_alert_id"] == mapping.event_id(a)   # alert creato comunque
    assert r["document_id"] is None                   # documento non creato (non blocca)


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            fails += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - fails}/{len(fns)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_run())
