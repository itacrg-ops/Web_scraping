"""Endpoint di liveness/readiness (probe Kubernetes e healthcheck compose)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict[str, str]:
    # TODO: verificare dipendenze critiche (DB, Redis) quando cablate.
    return {"status": "ready"}
