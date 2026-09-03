"""Workflow di screening (scaffold).

Orchestrazione durevole con Temporal: sequenza minima fetch → extract.
La pipeline completa (Broad→Targeted→Deep Dive→Alternative, early-termination,
classificazione FATF, AMI, pubblicazione su SVI) va costruita qui.
"""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import extract_content, fetch_source


@workflow.defn
class ScreeningWorkflow:
    @workflow.run
    async def run(self, url: str) -> dict:
        retry = RetryPolicy(maximum_attempts=3)
        raw = await workflow.execute_activity(
            fetch_source, url,
            start_to_close_timeout=timedelta(seconds=60), retry_policy=retry,
        )
        doc = await workflow.execute_activity(
            extract_content, raw,
            start_to_close_timeout=timedelta(seconds=60), retry_policy=retry,
        )
        return doc
