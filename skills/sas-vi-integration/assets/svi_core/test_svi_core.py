"""Test di svi_core (offline, senza rete):

    python test_svi_core.py      # oppure: pytest test_svi_core.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from svi_core import SviAlert, build_alerting_payload, publish, reset_idempotency  # noqa: E402
from svi_core import auth as _auth  # noqa: E402
from svi_core import client as _client  # noqa: E402
from svi_core.config import settings  # noqa: E402

ALERT = SviAlert(
    business_key="case-123", entity_id="00743110157", entity_label="ACME S.r.l.",
    score=82, trigger_text="Categorie FATF: … • AMI = 82",
    enrichment={"risk_level": "ALTO", "fatf_categories": "Corruption; ML"},
)


def test_event_id_deterministic():
    assert ALERT.event_id() == SviAlert(business_key="case-123", entity_id="x").event_id()
    assert ALERT.event_id() != SviAlert(business_key="case-999", entity_id="x").event_id()


def test_envelope_shape():
    settings.svi_entity_type = "Soggetto"
    settings.svi_queue = "queue_test"
    settings.svi_alert_type_code = "strategy_default"
    settings.svi_alert_origin = ""
    settings.svi_send_enrichment = False
    p = build_alerting_payload(ALERT, settings)
    assert p["jsonLayout"] == "flat"
    ev = p["alertingEvents"][0]
    assert "domainId" not in ev
    assert ev["actionableEntityType"] == "Soggetto"
    assert ev["actionableEntityId"] == "00743110157"
    assert ev["actionableEntityLabel"] == "ACME S.r.l."
    assert ev["score"] == 82
    assert ev["alertTypeCode"] == "strategy_default"
    assert ev["recommendedQueueId"] == "queue_test"
    assert "enrichment" not in p                      # gated off
    # label: fallback all'id quando manca
    ev2 = build_alerting_payload(SviAlert(business_key="k", entity_id="ID9"), settings)["alertingEvents"][0]
    assert ev2["actionableEntityLabel"] == "ID9"
    # enrichment on → array collegato via alertingEventId
    settings.svi_send_enrichment = True
    p2 = build_alerting_payload(ALERT, settings)
    assert p2["enrichment"][0]["alertingEventId"] == ALERT.event_id()
    assert p2["enrichment"][0]["risk_level"] == "ALTO"
    settings.svi_send_enrichment = False


def test_mock_publish_idempotent():
    settings.svi_mode = "mock"
    reset_idempotency()
    r1 = asyncio.run(publish(SviAlert(business_key="A", entity_id="1")))
    r2 = asyncio.run(publish(SviAlert(business_key="A", entity_id="1")))
    assert r1["deduplicated"] is False and r2["deduplicated"] is True
    assert r1["svi_alert_id"] == r2["svi_alert_id"] and r1["svi_alert_id"].startswith("svi-mock-")


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._p, self.content = status, payload, b"{}"
        self.request = httpx.Request("POST", "https://viya.example/svi-alert/alertingEvents")

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(str(self.status_code), request=self.request, response=self)


class _Client:
    def __init__(self, resp):
        self._r = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return self._r

    async def get(self, *a, **k):
        return self._r


def _run_live(resp, alert):
    settings.svi_mode = "live"
    settings.svi_queue = "queue_test"
    settings.svi_alert_type_code = "strategy_default"
    reset_idempotency()
    oc, ob = _client.httpx.AsyncClient, _auth.bearer

    async def _fb(_c, _cfg):
        return "tok"

    _client.httpx.AsyncClient = lambda *a, **k: _Client(resp)
    _auth.bearer = _fb
    try:
        return asyncio.run(publish(alert))
    finally:
        _client.httpx.AsyncClient = oc
        _auth.bearer = ob
        settings.svi_mode = "mock"


def test_live_1008_is_idempotent():
    a = SviAlert(business_key="DUP", entity_id="1")
    r = _run_live(_Resp(500, {"errorCode": 1008, "message": "data error"}), a)
    assert r["deduplicated"] is True and r["svi_alert_id"] == a.event_id()


def test_live_201_created():
    a = SviAlert(business_key="OK", entity_id="1")
    r = _run_live(_Resp(201, {"links": []}), a)
    assert r["deduplicated"] is False and r["svi_alert_id"] == a.event_id()


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
