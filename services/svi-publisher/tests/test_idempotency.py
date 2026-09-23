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
    """Sostituto di httpx.AsyncClient. `spec` è una risposta unica (per ogni POST/GET),
    un dict {sottostringa-url: risposta} per instradare chiamate diverse
    (es. /svi-datahub/documents vs /svi-alert/alertingEvents), oppure una LISTA
    consumata in ordine, una voce per chiamata: risposta o eccezione da sollevare
    (es. [httpx.ReadTimeout(...), <1008>] = timeout, poi 1008 al retry)."""
    calls = 0

    def __init__(self, spec):
        self._spec = spec

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _pick(self, url: str) -> _FakeResp:
        _FakeClient.calls += 1
        if isinstance(self._spec, list):
            item = self._spec.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
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


_1008 = {"errorCode": 1008, "message": "A data error occurred"}


def _run_live(spec, alert: dict, load_entity: bool = False, dedup_on_1008: bool = False,
              reset: bool = True, deadline: float = 90.0) -> dict:
    """Esegue publish_alert nel ramo live con client/auth finti, poi ripristina.
    `reset=False` conserva cache e marcatori tra due chiamate (retry di Temporal)."""
    settings.svi_mode = "live"
    settings.svi_load_entity = load_entity
    settings.svi_dedup_on_1008 = dedup_on_1008
    settings.svi_queue = "queue_test"
    settings.svi_alert_type_code = "strategy_default"
    settings.svi_retry_backoff = 0.0          # niente attese reali nei test
    settings.svi_publish_deadline = deadline
    if reset:
        svi_client.reset_idempotency()
    _FakeClient.calls = 0
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
        settings.svi_retry_backoff = 1.5
        settings.svi_publish_deadline = 90.0


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
    """errorCode 1008 è ambiguo (config errata vs duplicato): senza un tentativo
    precedente ambiguo NON va mascherato da successo → rifiuto terminale visibile."""
    a = {**ALERT, "screening_id": "ERR-1008"}
    try:
        _run_live(_FakeResp(500, _1008), a)
    except svi_client.SviRejected:
        return
    raise AssertionError("un 1008 senza tentativi ambigui deve sollevare SviRejected")


def test_live_1008_after_ambiguous_timeout_is_duplicate():
    """Il POST crea l'alert ma la risposta va in timeout; il retry riceve 1008:
    è il NOSTRO alert già creato → duplicato, non un errore."""
    a = {**ALERT, "screening_id": "AMB-1"}
    r = _run_live([httpx.ReadTimeout("lettura scaduta"), _FakeResp(500, _1008)], a)
    assert r["deduplicated"] is True
    assert r["svi_alert_id"] == mapping.event_id(a)


def test_live_1008_after_connect_error_is_rejected():
    """Connessione mai stabilita = richiesta mai arrivata: il 1008 successivo NON può
    essere un nostro duplicato → resta un rifiuto terminale."""
    a = {**ALERT, "screening_id": "AMB-2"}
    try:
        _run_live([httpx.ConnectError("rifiutata"), _FakeResp(500, _1008)], a)
    except svi_client.SviRejected:
        return
    raise AssertionError("ConnectError + 1008 deve restare SviRejected")


def test_live_1008_on_temporal_retry_after_ambiguous_call():
    """Prima chiamata: solo timeout → fallisce (il worker riceve 502 e Temporal
    ritenta). Seconda chiamata: 1008 → riconosciuto come duplicato del tentativo
    ambiguo precedente."""
    a = {**ALERT, "screening_id": "AMB-3"}
    try:
        _run_live([httpx.ReadTimeout("t")] * 4, a)
        raise AssertionError("solo timeout: la prima chiamata deve fallire")
    except httpx.TransportError:
        pass
    r = _run_live([_FakeResp(500, _1008)], a, reset=False)
    assert r["deduplicated"] is True


def test_retry_respects_publish_deadline():
    """Nessun nuovo tentativo se potrebbe sforare SVI_PUBLISH_DEADLINE (il worker ha
    un suo timeout e deve ricevere la risposta prima)."""
    a = {**ALERT, "screening_id": "DL-1"}
    try:
        _run_live([_FakeResp(504, {})] * 4, a, deadline=5.0)   # 5s < request_timeout (30s)
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 504
    assert _FakeClient.calls == 1, _FakeClient.calls
    try:
        _run_live([_FakeResp(504, {})] * 4, a, deadline=300.0)  # budget ampio: tutti i tentativi
    except httpx.HTTPStatusError:
        pass
    assert _FakeClient.calls == settings.svi_max_retries + 1, _FakeClient.calls


def test_endpoint_maps_errors_for_the_worker():
    """422 = rifiuto terminale (il worker non ritenta); 502 = transitorio."""
    from app import main

    req = httpx.Request("POST", "https://viya.example/x")
    cases = [
        (svi_client.SviRejected("1008"), 422),
        (httpx.HTTPStatusError("401", request=req, response=httpx.Response(401, request=req)), 422),
        (httpx.HTTPStatusError("503", request=req, response=httpx.Response(503, request=req)), 502),
        (httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req)), 502),
        (httpx.ConnectError("giù"), 502),
    ]
    orig = svi_client.publish_alert
    try:
        for exc, expected in cases:
            async def _boom(_alert, _exc=exc):
                raise _exc
            svi_client.publish_alert = _boom

            async def _call():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                             base_url="http://t") as c:
                    return await c.post("/publish/alert", json={"subject": "X", "ami_score": 1,
                                                                "risk_level": "BASSO"})
            status = asyncio.run(_call()).status_code
            assert status == expected, (type(exc).__name__, status, expected)
    finally:
        svi_client.publish_alert = orig


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
