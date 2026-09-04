"""Entrypoint del worker Temporal per lo scraping/screening.

Si connette a Temporal con retry (in dev il server può non essere ancora
pronto) e registra il workflow e le activity sulla task queue "scraping".
"""
from __future__ import annotations

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from activities import (
    classify_fatf,
    compute_ami,
    extract_content,
    fetch_source,
    persist_alert,
    publish_svi,
    resolve_entity,
)
from workflows import ScreeningWorkflow

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("worker-scraping")

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "temporal:7233")
TASK_QUEUE = os.getenv("SCRAPING_TASK_QUEUE", "scraping")


async def _connect_with_retry() -> Client:
    delay = 2
    while True:
        try:
            return await Client.connect(TEMPORAL_HOST)
        except Exception as exc:  # noqa: BLE001 — in dev attendiamo il server
            logger.warning("Temporal non raggiungibile (%s): retry tra %ss", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


async def main() -> None:
    client = await _connect_with_retry()
    logger.info("Connesso a Temporal su %s, task queue '%s'", TEMPORAL_HOST, TASK_QUEUE)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[ScreeningWorkflow],
        activities=[
            resolve_entity,
            fetch_source,
            extract_content,
            classify_fatf,
            compute_ami,
            publish_svi,
            persist_alert,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
