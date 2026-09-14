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
import re
import uuid
from typing import Any

# Namespace stabile per derivare un alertingEventId deterministico dalla business
# key (stesso screening → stesso id evento → idempotenza anche lato SVI).
_EVENT_NS = uuid.uuid5(uuid.NAMESPACE_URL, "adverse-media-screening/alertingEvent")


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


def event_id(alert: dict[str, Any]) -> str:
    """`alertingEventId` deterministico dalla business key (idempotenza lato SVI:
    stesso screening → stesso id evento → nessun duplicato)."""
    return str(uuid.uuid5(_EVENT_NS, business_key(alert)))


def trigger_text(alert: dict[str, Any], cfg=None) -> str:
    """Testo di innesco dell'alert (`alertTriggerText`): la motivazione leggibile,
    o in mancanza un riepilogo sintetico rischio/AMI/categorie.

    È l'UNICO campo che controlliamo ed è **già mostrato sulla scheda di dettaglio**
    (Page Template, field core "Alert-trigger text"). Con `SVI_TRIGGER_APPEND_SOURCES`
    vi accodiamo il blocco fonti, così i link compaiono sul dettaglio senza dover
    definire campi enrichment sul modello alert (schema di sistema, read-only)."""
    rat = rationale(alert)
    if rat:
        body = rat
    else:
        parts: list[str] = []
        if alert.get("risk_level"):
            parts.append(f"Rischio {alert['risk_level']}")
        if alert.get("ami_score") is not None:
            parts.append(f"AMI {alert['ami_score']}")
        cats = alert.get("fatf_categories") or []
        if cats:
            parts.append("categorie FATF: " + ", ".join(str(c) for c in cats))
        body = " · ".join(parts) or "Adverse media screening"
    if cfg is not None and getattr(cfg, "svi_trigger_append_sources", False):
        fonti = sources_text(alert.get("evidence"), limit=getattr(cfg, "svi_trigger_sources_limit", 5))
        if fonti:
            label = getattr(cfg, "svi_trigger_sources_label", "Fonti")
            body = f"{body}\n\n{label}:\n{fonti}"
        return body[:getattr(cfg, "svi_trigger_max_len", 3000)]
    return body[:2000]


def build_alerting_event(alert: dict[str, Any], cfg) -> dict[str, Any]:
    """Singolo oggetto `alertingEvent` (flat) da inserire nell'array `alertingEvents`
    dell'envelope (vedi `build_alerting_payload`). Struttura confermata dall'SVI Admin:
    **niente `domainId` / `actionableEntityLabel`**, presente `alertTriggerText`.

    Entità azionabile = soggetto (id = CF/P.IVA); `score` = AMI; `recommendedQueueId`
    = coda con acceptManualAlerts=true; `alertTypeCode` = tipo alert della strategia."""
    entity_id = alert.get("cf_piva") or business_key(alert)
    score = int(alert.get("ami_score") or 0)
    event: dict[str, Any] = {
        "alertingEventId": event_id(alert),
        "actionableEntityType": cfg.svi_entity_type,
        "actionableEntityId": entity_id,
        # Etichetta leggibile in coda = denominazione del soggetto (fallback all'id se
        # manca: es. soggetti senza CF/P.IVA). Senza questo campo SVI mostrerebbe l'id.
        "actionableEntityLabel": alert.get("subject") or entity_id,
        "score": score,
        "alertTypeCode": cfg.svi_alert_type_code or "strategy_default",
        "recommendedQueueId": cfg.svi_queue,
        "alertTriggerText": trigger_text(alert, cfg),
    }
    if cfg.svi_alert_origin:
        event["alertOriginCode"] = cfg.svi_alert_origin
    return event


def sources_text(evidence: list[dict[str, Any]] | None, limit: int = 10) -> str:
    """Elenco leggibile delle fonti/evidenze (`testata: url`, una per riga) per il
    campo enrichment `fonti`. Solo evidenze con URL; troncato a `limit`."""
    out: list[str] = []
    for e in (evidence or [])[:limit]:
        url = e.get("url")
        if not url:
            continue
        testata = e.get("testata") or e.get("title") or "fonte"
        out.append(f"{testata}: {url}")
    return "\n".join(out)


def build_enrichment(alert: dict[str, Any], cfg) -> dict[str, Any]:
    """Riga di `enrichment` (custom fields del dominio) collegata all'evento tramite
    `alertingEventId`. Valori stringa: SVI può validarne le chiavi sul modello dominio."""
    # I nomi delle chiavi vengono da config: devono combaciare con gli attributi del
    # dominio SVI, altrimenti l'enrichment è accettato ma non mostrato.
    enr: dict[str, Any] = {"alertingEventId": event_id(alert),
                           cfg.svi_enrich_key_source: cfg.svi_source_system}
    if alert.get("ami_score") is not None:
        enr[cfg.svi_enrich_key_ami] = str(alert.get("ami_score"))
    if alert.get("risk_level"):
        enr[cfg.svi_enrich_key_risk] = str(alert.get("risk_level"))
    cats = alert.get("fatf_categories") or []
    if cats:
        enr[cfg.svi_enrich_key_fatf] = "; ".join(str(c) for c in cats)
    if alert.get("disposition"):
        enr[cfg.svi_enrich_key_disposition] = str(alert.get("disposition"))
    rat = rationale(alert)
    if rat:
        enr[cfg.svi_enrich_key_rationale] = rat[:1000]
    # Sintesi della motivazione (primo driver, o inizio del rationale): campo breve da
    # mostrare in griglia, tenendo il full su una scheda di dettaglio.
    drivers = alert.get("drivers") or []
    summary = str(drivers[0]) if drivers else rat
    if summary:
        enr[cfg.svi_enrich_key_rationale_summary] = summary[:cfg.svi_rationale_summary_len]
    # Fonti/evidenze (link) come testo: "testata: url" per riga.
    fonti = sources_text(alert.get("evidence"))
    if fonti:
        enr[cfg.svi_enrich_key_sources] = fonti
    return enr


def build_scenario_fired_events(alert: dict[str, Any], cfg) -> list[dict[str, Any]]:
    """Findings → `scenarioFiredEvents`: una riga per categoria FATF (lo scenario che
    ha "sparato"), collegata all'evento. Concettualmente i driver del nostro AMI."""
    eid = event_id(alert)
    score = int(alert.get("ami_score") or 0)
    rat = rationale(alert)
    out: list[dict[str, Any]] = []
    for cat in (alert.get("fatf_categories") or []):
        slug = re.sub(r"[^a-z0-9]+", "_", str(cat).lower()).strip("_")
        out.append({
            "alertingEventId": eid,
            "scenarioId": (f"fatf_{slug}")[:64],
            "scenarioName": str(cat),
            "score": score,
            "messageTemplateText": rat or str(cat),
        })
    return out


def build_contributing_objects(alert: dict[str, Any], cfg) -> list[dict[str, Any]]:
    """Evidenze → `contributingObjects`: gli oggetti (articoli/fonti) che hanno
    contribuito all'alert, collegati all'evento."""
    eid = event_id(alert)
    out: list[dict[str, Any]] = []
    for e in _map_evidence(alert.get("evidence")):
        out.append({"alertingEventId": eid, **{k: v for k, v in e.items() if v is not None}})
    return out


def build_alerting_payload(alert: dict[str, Any], cfg) -> dict[str, Any]:
    """**Envelope completo** per `POST /svi-alert/alertingEvents` (jsonLayout flat).

    Struttura fornita dall'SVI Admin (il motivo dei precedenti `500 tdc.bad.request`:
    mancavano il discriminatore `jsonLayout` e l'involucro ad array):

        {"jsonLayout": "flat",
         "alertingEvents": [ <evento> ],
         "enrichment": [ <custom fields> ],            # opzionale
         "scenarioFiredEvents": [ <findings> ],        # opzionale
         "contributingObjects": [ <evidenze> ]}        # opzionale

    Le tre sezioni opzionali sono gated da config (off al primo test: minimizza le
    superfici di validazione lato dominio). Ogni riga è collegata all'evento via
    `alertingEventId`."""
    payload: dict[str, Any] = {
        "jsonLayout": "flat",
        "alertingEvents": [build_alerting_event(alert, cfg)],
    }
    if getattr(cfg, "svi_send_enrichment", False):
        payload["enrichment"] = [build_enrichment(alert, cfg)]
    if getattr(cfg, "svi_send_scenario_events", False):
        sfe = build_scenario_fired_events(alert, cfg)
        if sfe:
            payload["scenarioFiredEvents"] = sfe
    if getattr(cfg, "svi_send_contributing_objects", False):
        co = build_contributing_objects(alert, cfg)
        if co:
            payload["contributingObjects"] = co
    return payload
