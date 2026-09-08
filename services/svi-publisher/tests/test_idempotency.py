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

from app import svi_client  # noqa: E402
from app.config import settings  # noqa: E402

ALERT = {"subject": "ACME S.r.l.", "cf_piva": "00743110157", "cup": ["E51B21000000001"],
         "ami_score": 82, "risk_level": "ALTO", "fatf_categories": ["Money Laundering"],
         "drivers": ["AMI = 82"], "disposition": "ESCALATION_I_LIVELLO",
         "screening_id": "SCR-DEDUP-1", "evidence": []}


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
