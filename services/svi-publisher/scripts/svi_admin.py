"""Discovery READ-ONLY dell'API di amministrazione alert di SVI.

Serve a ricavare gli endpoint e le forme reali (domini, strategie, code,
dispositions, entity) PRIMA di scriptare la creazione via API. Non scrive nulla.

    docker compose -f docker-compose.dev.yml run --build --rm svi-publisher \
      python scripts/svi_admin.py

Riusa l'auth e il TLS del publisher (SVI_AUTH_MODE, SAS_*/VIYA_ENDPOINT,
SVI_VERIFY_TLS). Incolla l'output: da lì si scrivono le POST di creazione.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app import auth  # noqa: E402
from app.config import settings  # noqa: E402

# Endpoint candidati (gerarchia alert: Dominio → Strategia → Coda; + dispositions
# e metadata del modello dati). Alcuni possono dare 404: fa parte della discovery.
ENDPOINTS = [
    ("root svi-alert", "/svi-alert/"),
    ("alert · domains", "/svi-alert/domains?limit=50"),
    ("alert · strategies", "/svi-alert/strategies?limit=50"),
    ("alert · queues", "/svi-alert/queues?limit=50"),
    ("alert · dispositions", "/svi-alert/dispositions?limit=50"),
    ("root svi-datahub", "/svi-datahub/"),
    # Candidati per la CREAZIONE alert (leggi l'header Allow: POST = endpoint di create).
    ("alert · alertingEvents?", "/svi-alert/alertingEvents?limit=1"),
    ("alert · events?", "/svi-alert/events?limit=1"),
    ("alert · manualAlerts?", "/svi-alert/manualAlerts?limit=1"),
    ("datahub · alerts?", "/svi-datahub/alerts?limit=1"),
    ("datahub · manualAlerts?", "/svi-datahub/manualAlerts?limit=1"),
    ("datahub · documents (Allow)", "/svi-datahub/documents?limit=1"),
    ("datahub · entities?", "/svi-datahub/entities?limit=1"),
]

# Endpoint su cui provare anche OPTIONS (rivela i metodi ammessi / sotto-risorse).
OPTIONS_PROBES = ["/svi-alert/alerts", "/svi-datahub/documents"]


def get_token() -> str:
    if settings.svi_auth_mode == "token":
        if not settings.sas_bearer_token:
            print("ERRORE: SVI_AUTH_MODE=token ma SAS_BEARER_TOKEN è vuoto"); raise SystemExit(2)
        return settings.sas_bearer_token
    url, data, headers = auth.build_oauth_request(settings)
    with httpx.Client(verify=settings.verify_opt(), timeout=settings.svi_request_timeout) as c:
        r = c.post(url, data=data, headers=headers)
        r.raise_for_status()
        return r.json()["access_token"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Discovery admin SVI (read-only)")
    ap.add_argument("--probe", action="store_true",
                    help="POST con body vuoto per far rivelare a SAS media type/campi richiesti (NON crea)")
    args = ap.parse_args()
    print("SVI admin discovery ·", settings.viya_endpoint or "(endpoint vuoto!)")
    if settings.svi_ca_bundle and not os.path.exists(settings.svi_ca_bundle):
        print("ERRORE: SVI_CA_BUNDLE inesistente; usa SVI_VERIFY_TLS=false per il demo."); raise SystemExit(1)
    token = get_token()
    print("token OK (%d char)\n" % len(token))
    base = settings.viya_endpoint.rstrip("/")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(verify=settings.verify_opt(), timeout=settings.svi_request_timeout) as c:
        for label, path in ENDPOINTS:
            try:
                r = c.get(base + path, headers=h)
            except Exception as exc:  # noqa: BLE001
                print(f"[ERR] {label:32} {path}: {exc}"); continue
            print(f"[{r.status_code}] {label:32} {path}")
            allow = r.headers.get("allow") or r.headers.get("Allow")
            if allow:
                print("       Allow:", allow)
            try:
                j = r.json()
            except Exception:  # noqa: BLE001
                j = None
            if isinstance(j, dict) and isinstance(j.get("links"), list):
                for lk in j["links"][:40]:
                    print(f"       {str(lk.get('method', 'GET')):6} {str(lk.get('rel', '')):26} {lk.get('href', '')}")
            # Per gli endpoint chiave, dump COMPLETO del primo item (schema reale).
            if isinstance(j, dict) and j.get("items") and ("alertingEvents" in path or "/alerts?" in path):
                print("       item[0]:")
                print(json.dumps(j["items"][0], indent=2, ensure_ascii=False)[:3500])
                print()
                continue
            body = (r.text or "").strip().replace("\n", " ")
            if body:
                print("       body:", body[:1500])
            print()

        print("--- OPTIONS (metodi ammessi) ---")
        for path in OPTIONS_PROBES:
            try:
                r = c.request("OPTIONS", base + path, headers=h)
                allow = r.headers.get("allow") or r.headers.get("Allow") or "(nessun header Allow)"
                print(f"   OPTIONS {path}  → {r.status_code}  Allow: {allow}")
            except Exception as exc:  # noqa: BLE001
                print(f"   OPTIONS {path}: {exc}")

        if args.probe:
            print("\n--- PROBE CREATE (body vuoto → rivela media type/campi richiesti, NON crea) ---")
            for path in ("/svi-datahub/documents", "/svi-alert/alertingEvents"):
                try:
                    r = c.post(base + path, json={},
                               headers={**h, "Content-Type": "application/json"})
                    print(f"   POST {path} (json {{}}) → {r.status_code}")
                    print("       ", (r.text or "").strip()[:900])
                except Exception as exc:  # noqa: BLE001
                    print(f"   POST {path}: {exc}")


if __name__ == "__main__":
    main()
