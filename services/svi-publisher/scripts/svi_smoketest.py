"""Smoke-test LIVE verso SAS Visual Investigator — da eseguire DOVE l'app
raggiunge Viya (la sessione Claude ha egress bloccato verso engage.sas.com).

Cosa fa, in ordine, fermandosi al primo errore:
  1. AUTH   — ottiene un token OAuth (SASLogon) col grant configurato;
  2. DISCOVERY — sonda in sola lettura i servizi SVI (svi-datahub / svi-alert) e
     alcuni endpoint candidati del modello dati, per confermare path e nomi;
  3. PAYLOAD — costruisce documento+alert da un alert di esempio e li STAMPA
     (dry-run). Con --create effettua davvero la POST (scrive 1 documento+alert).

Uso (dalla root del repo, con .env valorizzato — vedi docs/SVI_GOLIVE.md):
    python services/svi-publisher/scripts/svi_smoketest.py            # dry-run
    python services/svi-publisher/scripts/svi_smoketest.py --create   # scrive davvero

NON stampa mai chiave/token/password. Le GET di discovery sono in sola lettura
(limit=1). --create scrive un solo documento+alert marcato come test.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app import auth, mapping  # noqa: E402
from app.config import settings  # noqa: E402

SAMPLE_ALERT = {
    "subject": "ACME Costruzioni S.r.l.", "tipo_soggetto": "persona_giuridica",
    "cf_piva": "00743110157", "cup": ["E51B21000000001"], "ami_score": 82,
    "risk_level": "ALTO", "fatf_categories": ["Corruption & Bribery", "Money Laundering"],
    "drivers": ["Categorie FATF: Corruption & Bribery", "AMI = 82 (smoke-test)"],
    "disposition": "ESCALATION_I_LIVELLO", "screening_id": "SMOKETEST-0001", "evidence": [],
}

# Endpoint di discovery in sola lettura. I path del modello dati (tipi documento,
# code) sono CANDIDATI: confermare quelli che rispondono 200 sull'ambiente reale.
DISCOVERY = [
    ("svi-datahub · documents", "/svi-datahub/documents?limit=1"),
    ("svi-alert · alertTypes", "/svi-alert/alertTypes?limit=50"),
    ("svi-alert · queues", "/svi-alert/queues?limit=50"),
    ("svi-alert · alerts", "/svi-alert/alerts?limit=1"),
]


def _line(ok: bool, msg: str) -> None:
    print(f"  [{'OK ' if ok else 'ERR'}] {msg}")


def get_token() -> str:
    print("\n1) AUTH — SASLogon")
    if settings.svi_auth_mode == "token":
        if not settings.sas_bearer_token:
            _line(False, "SVI_AUTH_MODE=token ma SAS_BEARER_TOKEN è vuoto nel .env")
            raise SystemExit(2)
        _line(True, f"bearer da .env ({len(settings.sas_bearer_token)} char) — "
                    "modalità token (es. da `sas-viya auth`)")
        return settings.sas_bearer_token
    print(f"  endpoint : {settings.token_url()}")
    print(f"  grant    : {settings.sas_oauth_grant}  ·  client_id: "
          f"{'(impostato)' if settings.sas_client_id else 'MANCANTE'}")
    if settings.svi_auth_mode == "broker":
        print(f"  modo     : broker → {settings.sas_token_broker_url}")
    url, data, headers = auth.build_oauth_request(settings)
    with httpx.Client(timeout=settings.svi_request_timeout, follow_redirects=False,
                      verify=settings.verify_opt()) as c:
        if settings.svi_auth_mode == "broker":
            r = c.get(settings.sas_token_broker_url)
        else:
            r = c.post(url, data=data, headers=headers)
    if r.status_code != 200:
        _line(False, f"token HTTP {r.status_code}: {r.text[:200]}")
        raise SystemExit(2)
    body = r.json()
    tok = body.get("access_token", "")
    _line(True, f"token ottenuto ({len(tok)} char), expires_in={body.get('expires_in')}s, "
                f"scope={body.get('scope', '—')}")
    return tok


def discovery(token: str) -> None:
    print("\n2) DISCOVERY — servizi SVI e modello dati (sola lettura)")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    base = settings.viya_endpoint.rstrip("/")
    with httpx.Client(timeout=settings.svi_request_timeout, verify=settings.verify_opt()) as c:
        # 2a. Root dei servizi: elenca i link/operazioni esposti (discovery SAS Viya).
        for root in ("/svi-datahub/", "/svi-alert/"):
            try:
                r = c.get(base + root, headers=headers)
            except Exception as exc:  # noqa: BLE001
                _line(False, f"root {root}: {exc}"); continue
            print(f"  --- {root}  (HTTP {r.status_code}) ---")
            try:
                j = r.json()
                links = j.get("links") if isinstance(j, dict) else None
            except Exception:  # noqa: BLE001
                links = None
            if isinstance(links, list):
                for lk in links[:30]:
                    print(f"      {str(lk.get('method', 'GET')):6} {str(lk.get('rel', '')):24} {lk.get('href', '')}")
            else:
                print("      body:", (r.text or "").strip()[:1200])
        # 2b. Endpoint candidati: stampa stato, header Allow (sui 405) e un estratto del corpo.
        for label, path in DISCOVERY:
            try:
                r = c.get(base + path, headers=headers)
            except Exception as exc:  # noqa: BLE001
                _line(False, f"{label}: {exc}")
                continue
            ok = r.status_code < 300
            allow = r.headers.get("allow") or r.headers.get("Allow")
            extra = f"  Allow: {allow}" if (r.status_code == 405 and allow) else ""
            _line(ok, f"{label:28} HTTP {r.status_code}  {path}{extra}")
            body = (r.text or "").strip().replace("\n", " ")
            if body:
                print("        body:", body[:2000])
    print("  → Cerca nei link/corpi qui sopra i valori reali di documentType / alertType /")
    print("    queue e mettili in SVI_OBJECT_TYPE / SVI_ALERT_TYPE / SVI_QUEUE.")


def payload(token: str, create: bool) -> None:
    print("\n3) PAYLOAD — mappatura alert → SVI (business key: "
          f"{mapping.business_key(SAMPLE_ALERT)})")
    document = mapping.build_document(SAMPLE_ALERT, settings)
    print("  --- documento Data Hub ---")
    print(json.dumps(document, indent=2, ensure_ascii=False))
    if not create:
        alert = mapping.build_alert(SAMPLE_ALERT, "<documentId>", settings)
        print("  --- alert (dry-run, documentId placeholder) ---")
        print(json.dumps(alert, indent=2, ensure_ascii=False))
        print("\n  (dry-run: nessuna scrittura. Ripeti con --create per creare davvero.)")
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "Accept": "application/json"}
    with httpx.Client(timeout=settings.svi_request_timeout, verify=settings.verify_opt()) as c:
        print("\n  POST documento →", settings.datahub_base() + "/documents")
        rd = c.post(settings.datahub_base() + "/documents", json=document, headers=headers)
        _line(rd.status_code < 300, f"documento HTTP {rd.status_code}: {rd.text[:300]}")
        if rd.status_code >= 300:
            raise SystemExit(3)
        doc_id = (rd.json() or {}).get("id")
        alert = mapping.build_alert(SAMPLE_ALERT, doc_id, settings)
        print("  POST alert →", settings.alerts_base() + "/alerts")
        ra = c.post(settings.alerts_base() + "/alerts", json=alert, headers=headers)
        _line(ra.status_code < 300, f"alert HTTP {ra.status_code}: {ra.text[:300]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Smoke-test live SVI")
    ap.add_argument("--create", action="store_true", help="scrive davvero 1 documento+alert (default: dry-run)")
    ap.add_argument("--skip-discovery", action="store_true")
    args = ap.parse_args()

    print("=" * 64)
    print("SVI smoke-test  ·  mode:", settings.svi_mode, " endpoint:", settings.viya_endpoint or "(vuoto!)")
    if settings.svi_ca_bundle:
        print("TLS: verifica attiva con CA bundle:", settings.svi_ca_bundle)
    elif not settings.svi_verify_tls:
        print("TLS: ⚠ verifica DISATTIVATA (SVI_VERIFY_TLS=false) — solo per demo self-signed")
    print("=" * 64)
    if settings.svi_ca_bundle and not os.path.exists(settings.svi_ca_bundle):
        print(f"ERRORE: SVI_CA_BUNDLE punta a un file inesistente qui: {settings.svi_ca_bundle}")
        print("  → per il demo usa SVI_VERIFY_TLS=false e lascia SVI_CA_BUNDLE vuoto,")
        print("    oppure monta/copia il certificato a quel percorso nel container.")
        raise SystemExit(1)
    if settings.svi_mode != "live":
        print("ATTENZIONE: SVI_MODE non è 'live'. La pipeline resterebbe in mock.")
    if not settings.viya_endpoint and settings.svi_auth_mode != "broker":
        print("ERRORE: VIYA_ENDPOINT non impostato in .env."); raise SystemExit(1)

    token = get_token()
    if not args.skip_discovery:
        discovery(token)
    payload(token, args.create)
    print("\nFatto.")


if __name__ == "__main__":
    main()
