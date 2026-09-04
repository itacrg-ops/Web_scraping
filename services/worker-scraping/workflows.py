"""Workflow di screening (walking skeleton).

Orchestrazione durevole con Temporal: fetch → extract → classify FATF → AMI →
pubblicazione SVI → persistenza. La pipeline reale (ricerca progressiva,
Victim-Bystander, materialità CUP, ecc.) si costruisce estendendo questa.
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
    )

_RETRY = RetryPolicy(maximum_attempts=3)
_TIMEOUT = timedelta(seconds=60)


@workflow.defn
class ScreeningWorkflow:
    @workflow.run
    async def run(self, req: dict) -> dict:
        raw = await workflow.execute_activity(
            fetch_source, req["seed_url"], start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )
        doc = await workflow.execute_activity(
            extract_content, raw, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )
        classification = await workflow.execute_activity(
            classify_fatf, doc["text"], start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )
        subject = {
            "denominazione": req["denominazione"],
            "cf_piva": req.get("cf_piva"),
            "cup": req.get("cup", []),
        }
        ami = await workflow.execute_activity(
            compute_ami, args=[subject, classification],
            start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
        )

        alert_payload = {
            "subject": subject["denominazione"],
            "cf_piva": subject["cf_piva"],
            "cup": subject["cup"],
            "ami_score": ami["ami_score"],
            "risk_level": ami["risk_level"],
            "fatf_categories": classification.get("fatf_categories", []),
            "drivers": ami["drivers"],
            "disposition": ami["disposition"],
        }

        svi_alert_id = await workflow.execute_activity(
            publish_svi, alert_payload, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )

        alert_create = {**alert_payload, "screening_id": req["screening_id"], "svi_alert_id": svi_alert_id}
        alert_id = await workflow.execute_activity(
            persist_alert, alert_create, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )

        return {"alert_id": alert_id, "svi_alert_id": svi_alert_id, "ami_score": ami["ami_score"]}
