"""Contratto canonico neutro rispetto al dominio per la pubblicazione in SAS VI.

L'idea: `svi_core` non sa nulla del dominio dell'applicazione. Ogni app scrive un
piccolo **adapter** che traduce il proprio oggetto (un alert AML, un caso di frode,
una segnalazione…) in un `SviAlert`; `svi_core` costruisce l'envelope e pubblica.
Così la conoscenza dura di SAS VI (auth, envelope, retry, idempotenza) sta in un solo
posto e si riusa senza copiarla.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# Namespace stabile per derivare un alertingEventId deterministico dalla business key
# (stessa chiave → stesso id evento → idempotenza anche lato SVI: i duplicati sono
# rifiutati con errorCode 1008, che il client tratta come "già pubblicato").
_EVENT_NS = uuid.uuid5(uuid.NAMESPACE_URL, "sas-vi-integration/alertingEvent")


@dataclass
class SviAlert:
    """Alert canonico da pubblicare in SAS VI. Popolato dall'adapter dell'app.

    Campi minimi obbligatori: `business_key`, `entity_id`. Tutto il resto è opzionale.
    `entity_type` / `alert_type_code` / `queue_id` / `origin_code` NON stanno qui: sono
    deployment-specific e vengono dalla config (`SviConfig`), non dal singolo alert.
    """
    business_key: str                 # chiave d'idempotenza stabile (es. id screening/caso)
    entity_id: str                    # actionableEntityId (id dell'entità azionabile)
    entity_label: str | None = None   # actionableEntityLabel (default: entity_id) — nome leggibile
    score: int = 0                    # score core dell'alert (es. punteggio di rischio)
    trigger_text: str = ""            # alertTriggerText: motivazione leggibile (mostrata di default)
    # Campi custom → finiscono in enrichmentJson sull'alert (mostrati via Page Builder).
    # Valori stringa: SVI li memorizza comunque; la visualizzazione è config di pagina.
    enrichment: dict[str, Any] = field(default_factory=dict)
    # Findings → scenarioFiredEvents (opz.): ogni dict con scenarioId/scenarioName/score/…
    scenario_events: list[dict[str, Any]] = field(default_factory=list)
    # Oggetti che hanno contribuito (evidenze/transazioni) → contributingObjects (opz.).
    contributing_objects: list[dict[str, Any]] = field(default_factory=list)

    def event_id(self) -> str:
        """alertingEventId deterministico (idempotenza)."""
        return str(uuid.uuid5(_EVENT_NS, self.business_key))
