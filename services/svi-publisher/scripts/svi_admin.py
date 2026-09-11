"""Discovery READ-ONLY dell'API di amministrazione alert di SVI.

Serve a ricavare gli endpoint e le forme reali (domini, strategie, code,
dispositions, entity) PRIMA di scriptare la creazione via API. Non scrive nulla.

    docker compose -f docker-compose.dev.yml run --build --rm svi-publisher \
      python scripts/svi_admin.py

Riusa l'auth e il TLS del publisher (SVI_AUTH_MODE, SAS_*/VIYA_ENDPOINT,
SVI_VERIFY_TLS). Incolla l'output: da lì si scrivono le POST di creazione.
"""
from __future__ import annotations

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
    ("admin-metadata (guess)", "/svi-admin-metadata/"),
    ("data-model (guess)", "/svi-data-model/"),
    ("datahub · entityTypes (guess)", "/svi-datahub/entityTypes?limit=50"),
]


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
            body = (r.text or "").strip().replace("\n", " ")
            if body:
                print("       body:", body[:1500])
            print()


if __name__ == "__main__":
    main()
