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


def build_alerting_event(alert: dict[str, Any], cfg) -> dict[str, Any]:
    """Alerting event SVI (flat): il motore lo trasforma in alert nella coda.
    `POST /svi-alert/alertingEvents`, media type
    `application/vnd.sas.investigation.triage.alerting.data.flat`.

    Entità azionabile = soggetto (id = CF/P.IVA, label = denominazione); `score` =
    AMI; `recommendedQueueId` = coda con acceptManualAlerts=true. L'`enrichment`
    (AMI/FATF/motivazione) è opzionale (SVI può validarne le chiavi sul dominio)."""
    label = alert.get("subject") or ""
    entity_id = alert.get("cf_piva") or business_key(alert)
    score = int(alert.get("ami_score") or 0)
    event: dict[str, Any] = {
        "domainId": cfg.svi_domain_id,
        "actionableEntityType": cfg.svi_entity_type,
        "actionableEntityId": entity_id,
        "actionableEntityLabel": label,
        "score": score,
        "recommendedQueueId": cfg.svi_queue,
        "alertTypeCode": cfg.svi_alert_type_code or "DEFAULT",
    }
    if cfg.svi_alert_origin:
        event["alertOriginCode"] = cfg.svi_alert_origin
    if getattr(cfg, "svi_send_enrichment", False):
        enr = {"source": cfg.svi_source_system}
        if alert.get("ami_score") is not None:
            enr["ami_score"] = str(alert.get("ami_score"))
        if alert.get("risk_level"):
            enr["risk_level"] = str(alert.get("risk_level"))
        cats = alert.get("fatf_categories") or []
        if cats:
            enr["fatf_categories"] = "; ".join(str(c) for c in cats)
        if alert.get("disposition"):
            enr["disposition"] = str(alert.get("disposition"))
        rat = rationale(alert)
        if rat:
            enr["rationale"] = rat[:1000]
        event["enrichment"] = enr
    return event
