"""API back-end (edge) dell'Adverse Media Screening.

È l'**unico confine di fiducia** verso la console di amministrazione React:
autentica, autorizza (RBAC — TODO Entra ID/JWT), valida e scrive l'audit.
La SPA non accede mai direttamente a DB/coda/LLM/SAS.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import alerts, health, sources

app = FastAPI(
    title="Adverse Media Screening — API",
    version="0.1.0",
    summary="Back-end edge (config, observability, orchestrazione) — pilota MASE/FSC",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(sources.router)
app.include_router(alerts.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "api", "env": settings.app_env}
