"""API back-end (edge) dell'Adverse Media Screening.

È l'**unico confine di fiducia** verso la console di amministrazione React:
autentica, autorizza (RBAC — TODO Entra ID/JWT), valida e scrive l'audit.
La SPA non accede mai direttamente a DB/coda/LLM/SAS.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import require_user
from app.config import settings
from app.db import init_db
from app.routers import alerts, health, screening, sources


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Adverse Media Screening — API",
    version="0.2.0",
    summary="Back-end edge (config, observability, orchestrazione) — pilota MASE/FSC",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(sources.router, dependencies=[Depends(require_user)])
app.include_router(alerts.router)  # auth per-route (GET: utente, POST: interno)
app.include_router(screening.router, dependencies=[Depends(require_user)])


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "api", "env": settings.app_env}
