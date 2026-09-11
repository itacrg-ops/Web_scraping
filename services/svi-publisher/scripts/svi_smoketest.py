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


def _self_id(obj: dict) -> str | None:
    for lk in obj.get("links", []):
        if lk.get("rel") == "self":
            return (lk.get("href") or "").rsplit("/", 1)[-1]
    return None


def _summ_queues(j: dict) -> list[str]:
    """Per ogni coda: id · dominio · se accetta alert manuali (→ target valido)."""
    out = []
    for q in (j.get("items") or []):
        out.append(f"{_self_id(q) or q.get('name')}  domain={q.get('domainId')}  "
                   f"acceptManualAlerts={q.get('acceptManualAlerts')}")
    return out or ["(nessuna coda)"]


def _summ_alert(j: dict) -> list[str]:
    """Campi salienti di un alert esistente (modello per la creazione)."""
    items = j.get("items") or []
    if not items:
        return ["(nessun alert esistente da cui dedurre lo schema)"]
    it = items[0]
    qref = next((lk.get("href") for lk in it.get("links", []) if lk.get("rel") == "queue"), None)
    keys = ["domainId", "actionableEntityType", "actionableEntityId", "actionableEntityLabel",
            "initialScore", "currentScore", "highScore", "alertOriginCode", "alertType", "status"]
    lines = [f"{k}={it.get(k)}" for k in keys if k in it]
    lines.append(f"queue={qref}")
    lines.append("tutti i campi: " + ", ".join(list(it.keys())))
    return lines


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
            j = None
            if ok:
                try:
                    j = r.json()
                except Exception:  # noqa: BLE001
                    j = None
            if j is not None and "/queues" in path:
                for ln in _summ_queues(j):
                    print("        queue:", ln)
            elif j is not None and "/alerts" in path:
                for ln in _summ_alert(j):
                    print("        alert:", ln)
            else:
                body = (r.text or "").strip().replace("\n", " ")
                if body:
                    print("        body:", body[:800])
    print("  → Metti gli id reali in .env: SVI_DOMAIN_ID (domainId), SVI_ENTITY_TYPE")
    print("    (entity type), SVI_QUEUE (queueId con acceptManualAlerts=true).")


def payload(token: str, create: bool) -> None:
    print("\n3) PAYLOAD — alerting event SVI (flat) · business key:",
          mapping.business_key(SAMPLE_ALERT))
    event = mapping.build_alerting_event(SAMPLE_ALERT, settings)
    print(json.dumps(event, indent=2, ensure_ascii=False))
    missing = [k for k in ("svi_domain_id", "svi_queue") if not getattr(settings, k)]
    if missing:
        print("  ⚠ mancano in .env:", ", ".join(m.upper() for m in missing),
              "→ necessari (SVI_DOMAIN_ID / SVI_QUEUE).")
    if not create:
        print("\n  (dry-run: nessuna scrittura. Ripeti con --create per creare davvero.)")
        return
    mt = settings.svi_alertingevent_media_type
    headers = {"Authorization": f"Bearer {token}", "Content-Type": mt, "Accept": "application/json"}
    url = settings.alerts_base() + "/alertingEvents"
    with httpx.Client(timeout=settings.svi_request_timeout, verify=settings.verify_opt()) as c:
        print("\n  POST alerting event (array) →", url)
        ra = c.post(url, json=[event], headers=headers)   # collezione: body = array
        _line(ra.status_code < 300, f"alertingEvents HTTP {ra.status_code}: {ra.text[:800]}")


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
