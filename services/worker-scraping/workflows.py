"""Workflow di screening (walking skeleton) con gate di Entity Resolution.

Orchestrazione durevole con Temporal:
  Entity Resolution (gate) → [se superata] fetch → extract → classify FATF →
  AMI → pubblicazione SVI → persistenza.
Se il gate NON è superato (soggetto ambiguo/irrisolto), NON si produce alcun
giudizio: si persiste un esito "da disambiguare" per la revisione umana
(abstain by default). La pipeline reale (ricerca progressiva, Victim-Bystander,
materialità CUP, ecc.) estende questa.
"""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import (
        classify_fatf,
        compute_ami,
        extract_content,
        fetch_source,
        persist_alert,
        publish_svi,
        resolve_entity,
        verify_subject_mention,
    )

_RETRY = RetryPolicy(maximum_attempts=3)
_TIMEOUT = timedelta(seconds=60)


@workflow.defn
class ScreeningWorkflow:
    @workflow.run
    async def run(self, req: dict) -> dict:
        subject = {
            "tipo_soggetto": req.get("tipo_soggetto", "persona_giuridica"),
            "denominazione": req["denominazione"],
            "nome": req.get("nome"),
            "cognome": req.get("cognome"),
            "data_nascita": req.get("data_nascita"),
            "cf_piva": req.get("cf_piva"),
            "cup": req.get("cup", []),
        }

        # --- GATE: Entity Resolution (obbligatoria prima del giudizio) ---
        resolution = await workflow.execute_activity(
            resolve_entity, subject, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )

        if not resolution.get("resolved"):
            # Abstain by default: nessun giudizio, escalation alla disambiguazione umana.
            held = {
                "screening_id": req["screening_id"],
                "subject": subject["denominazione"],
                "tipo_soggetto": subject["tipo_soggetto"],
                "cf_piva": subject["cf_piva"],
                "cup": subject["cup"],
                "ami_score": 0,
                "risk_level": "N/D",
                "fatf_categories": [],
                "drivers": ["Entity Resolution non superata: richiede disambiguazione umana"],
                "disposition": "HITL_ENTITY_RESOLUTION",
                "svi_alert_id": None,
                "entity_resolution": resolution,
            }
            alert_id = await workflow.execute_activity(
                persist_alert, held, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
            )
            return {"alert_id": alert_id, "gate": resolution.get("status"), "resolved": False}

        # Soggetto disambiguato: arricchisco con l'identità risolta.
        matched = resolution.get("matched") or {}
        if matched.get("cup"):
            subject["cup"] = subject["cup"] or matched.get("cup", [])

        # --- Pipeline di screening ---
        raw = await workflow.execute_activity(
            fetch_source, req["seed_url"], start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )
        doc = await workflow.execute_activity(
            extract_content, raw, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )
        classification = await workflow.execute_activity(
            classify_fatf, doc["text"], start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )
        ami = await workflow.execute_activity(
            compute_ami, args=[subject, classification],
            start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
        )

        # Verifica di menzione (non bloccante): il soggetto è citato nell'evidenza?
        mention_res = await workflow.execute_activity(
            verify_subject_mention, args=[subject, doc.get("text", "")],
            start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
        )
        drivers = list(ami["drivers"])
        if not mention_res.get("mentioned"):
            drivers.insert(
                0,
                "⚠ Soggetto non citato nell'evidenza raccolta: verificare attribuzione (possibile falsa attribuzione)",
            )

        alert_payload = {
            "subject": subject["denominazione"],
            "tipo_soggetto": subject["tipo_soggetto"],
            "cf_piva": subject["cf_piva"],
            "cup": subject["cup"],
            "ami_score": ami["ami_score"],
            "risk_level": ami["risk_level"],
            "fatf_categories": classification.get("fatf_categories", []),
            "drivers": drivers,
            "disposition": ami["disposition"],
        }

        svi_alert_id = await workflow.execute_activity(
            publish_svi, alert_payload, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )

        # Evidenza ancorata all'alert (URL, snippet, hash, timestamp, WARC).
        prov = doc.get("provenance") or {}
        text = doc.get("text") or ""
        evidence = []
        if prov.get("content_hash"):
            evidence.append({
                "url": doc.get("source"),
                "testata": doc.get("testata"),
                "title": doc.get("title"),
                "data": doc.get("date"),
                "snippet": text[:300],
                "content_hash": prov.get("content_hash"),
                "fetch_ts": prov.get("fetch_ts"),
                "bucket": prov.get("bucket"),
                "raw_key": prov.get("raw_key"),
                "warc_key": prov.get("warc_key"),
                "fonte_credibilita": None,
            })

        alert_create = {
            **alert_payload,
            "screening_id": req["screening_id"],
            "svi_alert_id": svi_alert_id,
            "entity_resolution": resolution,
            "evidence": evidence,
        }
        alert_id = await workflow.execute_activity(
            persist_alert, alert_create, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )

        return {
            "alert_id": alert_id,
            "svi_alert_id": svi_alert_id,
            "ami_score": ami["ami_score"],
            "resolved": True,
        }
