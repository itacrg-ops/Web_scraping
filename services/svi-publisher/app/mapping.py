"""Mappatura alert interno → payload SAS Visual Investigator (Data Hub + Alert).

Anti-corruption layer **puro** (nessun I/O): traduce il nostro alert canonico
(AMI, categorie FATF, motivazione, evidenze) nei due oggetti SVI:

  1. un **documento/record** nel Data Hub (`/svi-datahub/documents`), del tipo
     configurato (`SVI_OBJECT_TYPE`), con gli attributi del soggetto e delle
     evidenze;
  2. un **alert** (`/svi-alert/alerts`) del tipo/coda configurati, collegato al
     documento, con punteggio AMI e categorie.

I **nomi di tipo/coda/attributo esterno** sono deployment-specific (dipendono dal
data model SVI del cliente): vengono da `settings`, non sono cablati nel codice.
La **business key** rende la pubblicazione **idempotente** (stesso screening →
stesso `externalId` → nessun duplicato lato SVI e in cache).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def business_key(alert: dict[str, Any]) -> str:
    """Chiave d'affari deterministica per la dedup. Preferisce `screening_id`
    (un solo alert per screening); in mancanza, un hash del contenuto canonico."""
    sid = alert.get("screening_id")
    if sid:
        return f"ams-{sid}"
    canonical = {
        "subject": alert.get("subject"),
        "cf_piva": alert.get("cf_piva"),
        "cup": sorted(alert.get("cup") or []),
        "ami_score": alert.get("ami_score"),
        "risk_level": alert.get("risk_level"),
        "fatf_categories": sorted(alert.get("fatf_categories") or []),
    }
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return f"ams-{digest[:16]}"


def _map_evidence(evidence: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = []
    for e in evidence or []:
        out.append({
            "url": e.get("url"),
            "source": e.get("testata"),
            "title": e.get("title"),
            "date": e.get("data"),
            "snippet": e.get("snippet"),
            "contentHash": e.get("content_hash"),
            "credibility": e.get("fonte_credibilita"),
            "fetchTs": e.get("fetch_ts"),
            "warcKey": e.get("warc_key"),
        })
    return out


def rationale(alert: dict[str, Any]) -> str:
    """Motivazione leggibile dall'istruttore: i driver dell'AMI in un unico testo."""
    return " • ".join(str(d) for d in (alert.get("drivers") or []))


def build_document(alert: dict[str, Any], cfg) -> dict[str, Any]:
    """Documento/record del Data Hub (tipo oggetto configurato)."""
    key = business_key(alert)
    attributes: dict[str, Any] = {
        "subjectName": alert.get("subject"),
        "subjectType": alert.get("tipo_soggetto"),
        "taxId": alert.get("cf_piva"),
        "cupCodes": alert.get("cup") or [],
        "amiScore": alert.get("ami_score"),
        "riskLevel": alert.get("risk_level"),
        "fatfCategories": alert.get("fatf_categories") or [],
        "disposition": alert.get("disposition"),
        "rationale": rationale(alert),
        "evidence": _map_evidence(alert.get("evidence")),
        "sourceSystem": cfg.svi_source_system,
        cfg.svi_external_id_attr: key,
    }
    return {"objectType": cfg.svi_object_type, "externalId": key, "attributes": attributes}


def build_alert(alert: dict[str, Any], document_id: str | None, cfg) -> dict[str, Any]:
    """Alert SVI (tipo/coda configurati) collegato al documento del Data Hub."""
    key = business_key(alert)
    subject = alert.get("subject")
    ami = alert.get("ami_score")
    risk = alert.get("risk_level")
    payload: dict[str, Any] = {
        "alertType": cfg.svi_alert_type,
        "queue": cfg.svi_queue,
        "status": "NEW",
        "score": ami,
        "riskLevel": risk,
        "subject": subject,
        "categories": alert.get("fatf_categories") or [],
        "summary": f"AMI {ami} ({risk}) — {subject}",
        "disposition": alert.get("disposition"),
        "sourceSystem": cfg.svi_source_system,
        cfg.svi_external_id_attr: key,
    }
    if document_id:
        payload["documentId"] = document_id
    return payload
