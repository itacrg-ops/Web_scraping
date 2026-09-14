"""Smoke-test LIVE verso SAS Visual Investigator (usa svi_core).

Da eseguire DOVE l'app raggiunge Viya (con .env valorizzato). In ordine:
  1. AUTH      — token OAuth (SASLogon) col grant configurato;
  2. DISCOVERY — sonda in sola lettura svi-datahub/svi-alert (conferma path/nomi);
  3. PAYLOAD   — costruisce l'envelope da un SviAlert di esempio e lo STAMPA (dry-run);
     con --create lo POSTa davvero; con --diagnose isola il campo che causa un errore.

    python svi_smoketest.py                 # dry-run (stampa envelope)
    python svi_smoketest.py --create        # crea un alert di prova
    python svi_smoketest.py --create --unique   # id nuovo (evita la dedup)
    python svi_smoketest.py --diagnose      # varianti per isolare l'errore (non crea)

Non stampa mai chiave/token. svi_core deve essere accanto (stessa cartella assets).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from svi_core import SviAlert, auth, build_alerting_payload  # noqa: E402
from svi_core.config import settings  # noqa: E402


def _sample(unique: bool) -> SviAlert:
    bk = f"SMOKETEST-{int(time.time())}" if unique else "SMOKETEST-0001"
    return SviAlert(
        business_key=bk, entity_id="00743110157", entity_label="ACME S.r.l. (smoke-test)",
        score=82, trigger_text="Smoke-test svi_core • categorie: A; B • score 82",
        enrichment={"risk_level": "ALTO", "categories": "A; B"},
    )


DISCOVERY = [
    ("svi-alert · queues", "/svi-alert/queues?limit=50"),
    ("svi-alert · alertTypes", "/svi-alert/alertTypes?limit=50"),
    ("svi-alert · alerts", "/svi-alert/alerts?limit=1"),
]


def get_token() -> str:
    print("\n1) AUTH — SASLogon")
    if settings.svi_auth_mode == "token":
        if not settings.sas_bearer_token:
            print("  [ERR] SVI_AUTH_MODE=token ma SAS_BEARER_TOKEN vuoto"); raise SystemExit(2)
        print(f"  [OK ] bearer da .env ({len(settings.sas_bearer_token)} char)")
        return settings.sas_bearer_token
    print(f"  endpoint: {settings.token_url()}  grant: {settings.sas_oauth_grant}")
    url, data, headers = auth.build_oauth_request(settings)
    with httpx.Client(timeout=settings.svi_request_timeout, verify=settings.verify_opt()) as c:
        r = c.get(settings.sas_token_broker_url) if settings.svi_auth_mode == "broker" \
            else c.post(url, data=data, headers=headers)
    if r.status_code != 200:
        print(f"  [ERR] token HTTP {r.status_code}: {r.text[:200]}"); raise SystemExit(2)
    tok = r.json().get("access_token", "")
    print(f"  [OK ] token ottenuto ({len(tok)} char)")
    return tok


def discovery(token: str) -> None:
    print("\n2) DISCOVERY (sola lettura)")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    base = settings.viya_endpoint.rstrip("/")
    with httpx.Client(timeout=settings.svi_request_timeout, verify=settings.verify_opt()) as c:
        for label, path in DISCOVERY:
            try:
                r = c.get(base + path, headers=h)
            except Exception as exc:  # noqa: BLE001
                print(f"  [ERR] {label}: {exc}"); continue
            print(f"  [{r.status_code}] {label}  {path}")
            if r.status_code < 300 and "/queues" in path:
                for q in (r.json().get("items") or [])[:20]:
                    sid = next((l.get("href", "").rsplit("/", 1)[-1] for l in q.get("links", []) if l.get("rel") == "self"), None)
                    print(f"        queue: {sid or q.get('name')}  acceptManualAlerts={q.get('acceptManualAlerts')}")


def _post(c, url, body, token):
    mt = settings.svi_alertingevent_media_type
    return c.post(url, json=body, headers={"Authorization": f"Bearer {token}", "Content-Type": mt, "Accept": "application/json"})


def payload(token: str, create: bool, unique: bool) -> None:
    print("\n3) PAYLOAD — envelope alerting event (jsonLayout flat)")
    body = build_alerting_payload(_sample(unique), settings)
    print(json.dumps(body, indent=2, ensure_ascii=False))
    if not settings.svi_queue:
        print("  ⚠ SVI_QUEUE non impostato in .env (recommendedQueueId).")
    if not create:
        print("\n  (dry-run: nessuna scrittura. --create per creare davvero.)"); return
    url = settings.alerts_base() + "/alertingEvents"
    with httpx.Client(timeout=settings.svi_request_timeout, verify=settings.verify_opt()) as c:
        r = _post(c, url, body, token)
    ok = r.status_code < 300
    print(f"\n  [{'OK ' if ok else 'ERR'}] POST alertingEvents HTTP {r.status_code}: {r.text[:600]}")
    if not ok and ("1008" in (r.text or "")):
        print("  ↳ 1008: con alertTypeCode valido è un DUPLICATO (idempotenza) → usa --unique;")
        print("     senza alertTypeCode è obbligatorio (vedi --diagnose).")


def diagnose(token: str) -> None:
    print("\n3b) DIAGNOSE — isola il campo che innesca l'errore (non crea)")
    url = settings.alerts_base() + "/alertingEvents"

    def variant(label, mutate):
        body = build_alerting_payload(SviAlert(business_key=f"DIAG-{label}-{int(time.time())}",
                                               entity_id="00743110157", entity_label="diag", score=82,
                                               trigger_text="diag"), settings)
        mutate(body["alertingEvents"][0])
        with httpx.Client(timeout=settings.svi_request_timeout, verify=settings.verify_opt()) as c:
            r = _post(c, url, body, token)
        code = ""
        try:
            code = str((r.json() or {}).get("errorCode") or "")
        except Exception:  # noqa: BLE001
            pass
        print(f"   [{label:18}] HTTP {r.status_code}  errorCode={code or '—'}  {(r.text or '')[:120]}")

    variant("baseline", lambda e: None)
    variant("no-alertTypeCode", lambda e: e.pop("alertTypeCode", None))
    variant("no-queue", lambda e: e.pop("recommendedQueueId", None))
    print("   → stesso errorCode ovunque = problema di entità/strategia; cambia = quel campo.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Smoke-test live SAS VI (svi_core)")
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--unique", action="store_true")
    ap.add_argument("--diagnose", action="store_true")
    ap.add_argument("--skip-discovery", action="store_true")
    args = ap.parse_args()
    print("=" * 60)
    print("SVI smoke-test · mode:", settings.svi_mode, " endpoint:", settings.viya_endpoint or "(vuoto!)")
    if not settings.svi_verify_tls and not settings.svi_ca_bundle:
        print("TLS: ⚠ verifica DISATTIVATA (solo demo self-signed)")
    print("=" * 60)
    if not settings.viya_endpoint and settings.svi_auth_mode != "broker":
        print("ERRORE: VIYA_ENDPOINT non impostato."); raise SystemExit(1)
    token = get_token()
    if not args.skip_discovery:
        discovery(token)
    payload(token, args.create, args.unique)
    if args.diagnose:
        diagnose(token)
    print("\nFatto.")


if __name__ == "__main__":
    main()
