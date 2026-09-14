"""Ispezione/onboarding di un ambiente SAS VI (usa svi_core, sola lettura).

Serve a scoprire i valori da mettere nel `.env` di una nuova integrazione e a capire
come sono fatti gli alert dell'ambiente. Naviga il grafo reale dell'API (i metadati NON
stanno in un servizio a sé: vivono in svi-alert/svi-datahub) e dumpa un alert esistente
per verificare cosa viene memorizzato (es. `enrichmentJson`).

    python svi_inspect.py                 # discovery: root link + domini/strategie/code/alert
    python svi_inspect.py --alert <path>  # dump della definizione di uno specifico alert

Da eseguire dove l'app raggiunge Viya. Non stampa mai token.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from svi_core import auth  # noqa: E402
from svi_core.config import settings  # noqa: E402

KNOWN_ROOTS = ["/svi-datahub", "/svi-alert"]
PROBE = [
    "/svi-alert/domains?limit=20",
    "/svi-alert/strategies?limit=20",
    "/svi-alert/queues?limit=20",
    "/svi-alert/dispositions?limit=20",
    "/svi-alert/alertTypes?limit=20",
    "/svi-alert/alerts?limit=5",
]
# chiavi enrichment "tipiche": cerchiamo se un alert esistente le memorizza (enrichmentJson)
ENRICH_HINT = ["enrichmentJson", "risk_level", "fatf_categories", "rationale"]


def get_token() -> str:
    if settings.svi_auth_mode == "token":
        if not settings.sas_bearer_token:
            print("ERRORE: SVI_AUTH_MODE=token ma SAS_BEARER_TOKEN vuoto"); raise SystemExit(2)
        return settings.sas_bearer_token
    url, data, headers = auth.build_oauth_request(settings)
    with httpx.Client(verify=settings.verify_opt(), timeout=settings.svi_request_timeout) as c:
        r = c.get(settings.sas_token_broker_url) if settings.svi_auth_mode == "broker" \
            else c.post(url, data=data, headers=headers)
        r.raise_for_status()
        return r.json()["access_token"]


def _get(c, url, h):
    try:
        return c.get(url, headers=h)
    except Exception as exc:  # noqa: BLE001
        print(f"   [ERR] {url}: {exc}"); return None


def _self(obj):
    for lk in obj.get("links", []) if isinstance(obj, dict) else []:
        if lk.get("rel") == "self":
            return lk.get("href")
    return None


def _links(obj, indent="          "):
    for lk in (obj.get("links") or []) if isinstance(obj, dict) else []:
        print(f"{indent}{str(lk.get('rel','')):22} {str(lk.get('method','GET')):5} {lk.get('href','')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Ispezione ambiente SAS VI (svi_core)")
    ap.add_argument("--alert", metavar="PATH", help="dump di un alert (percorso completo, es. /svi-alert/alerts/<id>)")
    args = ap.parse_args()
    if not settings.viya_endpoint:
        print("ERRORE: VIYA_ENDPOINT non impostato."); raise SystemExit(1)
    token = get_token()
    print("token OK (%d char)" % len(token))
    base = settings.viya_endpoint.rstrip("/")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    with httpx.Client(verify=settings.verify_opt(), timeout=settings.svi_request_timeout) as c:
        if args.alert:
            r = _get(c, base + args.alert, h)
            if r is not None:
                print(f"[{r.status_code}] {args.alert}")
                txt = r.text or ""
                print(txt[:3000])
                found = [k for k in ENRICH_HINT if k in txt]
                print("\n→ chiavi trovate nell'alert:", found or "nessuna")
            return

        print("\n1) ROOT dei servizi (link)")
        for root in KNOWN_ROOTS:
            r = _get(c, base + root + "/", h)
            if r is None:
                continue
            print(f"  [{r.status_code}] {root}/")
            try:
                _links(r.json(), "       ")
            except Exception:  # noqa: BLE001
                pass

        print("\n2) ENDPOINT NOTI — item (id · name · label) + link")
        alert_url = None
        for path in PROBE:
            r = _get(c, base + path, h)
            if r is None:
                continue
            print(f"  [{r.status_code}] {path}")
            if r.status_code >= 400:
                continue
            try:
                items = (r.json() or {}).get("items") or []
            except Exception:  # noqa: BLE001
                items = []
            for it in items[:8]:
                iid = (_self(it) or "").rsplit("/", 1)[-1] or it.get("id")
                extra = ""
                if "/queues" in path:
                    extra = f"  acceptManualAlerts={it.get('acceptManualAlerts')}"
                if "/alertTypes" in path:
                    extra = f"  code={it.get('code')}"
                print(f"        - {iid}  name={it.get('name')} label={it.get('label')}{extra}")
                if "/alerts" in path or "/domains" in path:
                    _links(it)
            if "/alerts" in path and items and alert_url is None:
                alert_url = base + (_self(items[0]) or "")

        if alert_url:
            print("\n3) ALERT DI ESEMPIO — cosa viene memorizzato (es. enrichmentJson)")
            r = _get(c, alert_url, h)
            if r is not None and r.status_code < 400:
                txt = r.text or ""
                print("  URL:", alert_url)
                print(txt[:2500])
                found = [k for k in ENRICH_HINT if k in txt]
                print("\n  → chiavi trovate:", found or "nessuna")
                print("     enrichmentJson presente = i campi custom sono memorizzati")
                print("     (visualizzarli è config di pagina: Page Builder / Alert Grid).")

    print("\n→ Metti in .env: SVI_QUEUE (coda con acceptManualAlerts=true),",
          "SVI_ENTITY_TYPE, SVI_ALERT_TYPE_CODE.")


if __name__ == "__main__":
    main()
