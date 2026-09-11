"""Test della mappatura alert → payload SVI (funzioni pure) e della auth builder.

    pytest services/svi-publisher/tests/test_mapping.py
    python  services/svi-publisher/tests/test_mapping.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import auth, mapping  # noqa: E402
from app.config import settings  # noqa: E402

ALERT = {
    "subject": "ACME Costruzioni S.r.l.",
    "tipo_soggetto": "persona_giuridica",
    "cf_piva": "00743110157",
    "cup": ["E51B21000000001"],
    "ami_score": 82,
    "risk_level": "ALTO",
    "fatf_categories": ["Corruption & Bribery", "Money Laundering"],
    "drivers": ["Categorie FATF: Corruption & Bribery", "AMI = 82"],
    "disposition": "ESCALATION_I_LIVELLO",
    "screening_id": "SCR-123",
    "evidence": [
        {"url": "https://news.example/a", "testata": "news.example", "title": "Indagine",
         "data": "2026-01-02", "snippet": "…", "content_hash": "abc",
         "fetch_ts": "2026-01-02T10:00:00Z", "warc_key": "w/a.warc",
         "fonte_credibilita": "alta"},
    ],
}


def test_business_key_prefers_screening_id():
    assert mapping.business_key(ALERT) == "ams-SCR-123"
    # stesso screening → stessa chiave (idempotenza)
    assert mapping.business_key({**ALERT}) == "ams-SCR-123"


def test_business_key_hashes_content_when_no_screening_id():
    a = {**ALERT}
    a.pop("screening_id")
    k1 = mapping.business_key(a)
    assert k1.startswith("ams-") and len(k1) > 4
    # contenuto diverso → chiave diversa
    k2 = mapping.business_key({**a, "ami_score": 10})
    assert k1 != k2
    # ordine dei CUP/categorie irrilevante (canonicalizzazione)
    assert mapping.business_key({**a, "cup": list(reversed(a["cup"]))}) == k1


def test_build_document_maps_fields_and_evidence():
    doc = mapping.build_document(ALERT, settings)
    assert doc["objectType"] == settings.svi_object_type
    assert doc["externalId"] == "ams-SCR-123"
    at = doc["attributes"]
    assert at["subjectName"] == "ACME Costruzioni S.r.l."
    assert at["taxId"] == "00743110157"
    assert at["amiScore"] == 82
    assert at["fatfCategories"] == ["Corruption & Bribery", "Money Laundering"]
    assert at["rationale"].startswith("Categorie FATF")   # motivazione
    assert at[settings.svi_external_id_attr] == "ams-SCR-123"
    # evidenza mappata sui nomi SVI
    ev = at["evidence"][0]
    assert ev["url"] == "https://news.example/a"
    assert ev["source"] == "news.example"
    assert ev["contentHash"] == "abc"
    assert ev["credibility"] == "alta"


def test_build_alerting_event_schema():
    settings.svi_entity_type = "Soggetto"
    settings.svi_queue = "queue_test"
    settings.svi_alert_origin = ""
    settings.svi_alert_type_code = "strategy_default"
    e = mapping.build_alerting_event(ALERT, settings)
    # Struttura confermata dall'SVI Admin: NIENTE domainId / actionableEntityLabel.
    assert "domainId" not in e
    assert "actionableEntityLabel" not in e
    assert e["actionableEntityType"] == "Soggetto"
    assert e["actionableEntityId"] == "00743110157"          # CF/P.IVA del soggetto
    assert e["score"] == 82                                   # AMI
    assert e["recommendedQueueId"] == "queue_test"
    assert e["alertTypeCode"] == "strategy_default"
    assert e["alertTriggerText"].startswith("Categorie FATF")  # motivazione/driver
    # alertingEventId deterministico dalla business key (idempotenza lato SVI)
    assert e["alertingEventId"] == mapping.build_alerting_event(ALERT, settings)["alertingEventId"]
    assert e["alertingEventId"] == mapping.event_id(ALERT)
    assert "alertOriginCode" not in e                         # vuoto → omesso
    # alertOriginCode valorizzato → incluso
    settings.svi_alert_origin = "AdverseMedia"
    assert mapping.build_alerting_event(ALERT, settings)["alertOriginCode"] == "AdverseMedia"
    settings.svi_alert_origin = ""


def test_build_alerting_payload_envelope():
    settings.svi_entity_type = "Soggetto"
    settings.svi_queue = "queue_test"
    settings.svi_send_enrichment = False
    settings.svi_send_scenario_events = False
    settings.svi_send_contributing_objects = False
    # Minimo: solo il discriminatore flat + l'array alertingEvents (1 evento).
    p = mapping.build_alerting_payload(ALERT, settings)
    assert p["jsonLayout"] == "flat"
    assert isinstance(p["alertingEvents"], list) and len(p["alertingEvents"]) == 1
    assert p["alertingEvents"][0]["actionableEntityId"] == "00743110157"
    assert "enrichment" not in p and "scenarioFiredEvents" not in p and "contributingObjects" not in p
    # enrichment abilitato → array di 1 riga collegata all'evento (valori stringa)
    settings.svi_send_enrichment = True
    p2 = mapping.build_alerting_payload(ALERT, settings)
    enr = p2["enrichment"][0]
    assert enr["alertingEventId"] == mapping.event_id(ALERT)
    assert enr["ami_score"] == "82"
    assert enr["risk_level"] == "ALTO"
    assert "Corruption & Bribery" in enr["fatf_categories"]
    # scenario + contributing abilitati → una riga per categoria FATF / evidenza
    settings.svi_send_scenario_events = True
    settings.svi_send_contributing_objects = True
    p3 = mapping.build_alerting_payload(ALERT, settings)
    sfe = p3["scenarioFiredEvents"]
    assert {s["scenarioName"] for s in sfe} == set(ALERT["fatf_categories"])
    assert all(s["alertingEventId"] == mapping.event_id(ALERT) for s in sfe)
    co = p3["contributingObjects"]
    assert co[0]["url"] == "https://news.example/a"
    assert co[0]["alertingEventId"] == mapping.event_id(ALERT)
    settings.svi_send_enrichment = False
    settings.svi_send_scenario_events = False
    settings.svi_send_contributing_objects = False


def test_oauth_request_builder_is_pure_and_correct():
    settings.sas_client_id = "cid"
    settings.sas_client_secret = "secret"
    settings.viya_endpoint = "https://viya.example.org"
    settings.sas_oauth_grant = "client_credentials"
    url, data, headers = auth.build_oauth_request(settings)
    assert url == "https://viya.example.org/SASLogon/oauth/token"
    assert data["grant_type"] == "client_credentials"
    assert headers["Authorization"].startswith("Basic ")
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    # grant password aggiunge le credenziali utente
    settings.sas_oauth_grant = "password"
    settings.sas_username, settings.sas_password = "u", "p"
    _, data2, _ = auth.build_oauth_request(settings)
    assert data2["username"] == "u" and data2["password"] == "p"
    # ripristina i default per non inquinare gli altri test
    settings.sas_oauth_grant = "client_credentials"
    settings.viya_endpoint = ""


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            fails += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - fails}/{len(fns)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_run())
