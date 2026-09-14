"""Costruzione dell'envelope "alerting event" per SAS VI (funzione pura).

L'alert in SVI si crea con un **alerting event** (`POST /svi-alert/alertingEvents`),
NON con `POST /svi-alert/alerts` (sola lettura, 405). Il body è un **envelope** con
discriminatore `jsonLayout:"flat"` e sezioni ad **array**: senza di esso SVI risponde
`500 tdc.bad.request` (rifiuto di struttura, identico anche a body vuoto).

Media type obbligatorio (versionato):
`application/vnd.sas.investigation.triage.alerting.data.flat+json;version=1`
"""
from __future__ import annotations

from typing import Any

from .models import SviAlert


def build_alerting_payload(alert: SviAlert, cfg) -> dict[str, Any]:
    """Envelope completo per POST /svi-alert/alertingEvents.

    L'oggetto evento **non** ha `domainId` (implicito nella coda/strategia). Ha invece
    `actionableEntityLabel` = etichetta leggibile (default: id). `alertTypeCode` è
    **obbligatorio**: senza, SVI risponde `errorCode 1008`.
    """
    eid = alert.event_id()
    event: dict[str, Any] = {
        "alertingEventId": eid,
        "actionableEntityType": cfg.svi_entity_type,
        "actionableEntityId": alert.entity_id,
        "actionableEntityLabel": alert.entity_label or alert.entity_id,
        "score": int(alert.score or 0),
        "alertTypeCode": cfg.svi_alert_type_code or "strategy_default",
        "recommendedQueueId": cfg.svi_queue,
        "alertTriggerText": alert.trigger_text,
    }
    if cfg.svi_alert_origin:
        event["alertOriginCode"] = cfg.svi_alert_origin

    payload: dict[str, Any] = {"jsonLayout": "flat", "alertingEvents": [event]}

    if getattr(cfg, "svi_send_enrichment", False) and alert.enrichment:
        payload["enrichment"] = [{"alertingEventId": eid, **{k: str(v) for k, v in alert.enrichment.items()}}]
    if getattr(cfg, "svi_send_scenario_events", False) and alert.scenario_events:
        payload["scenarioFiredEvents"] = [{"alertingEventId": eid, **s} for s in alert.scenario_events]
    if getattr(cfg, "svi_send_contributing_objects", False) and alert.contributing_objects:
        payload["contributingObjects"] = [{"alertingEventId": eid, **o} for o in alert.contributing_objects]

    return payload
