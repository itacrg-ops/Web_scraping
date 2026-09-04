"""Client Temporal per avviare i workflow di screening dall'API."""
from __future__ import annotations

from temporalio.client import Client

from app.config import settings

_client: Client | None = None


async def get_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(settings.temporal_host)
    return _client
