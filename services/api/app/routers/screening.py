"""Avvio e stato di uno screening (walking skeleton end-to-end).

`POST /api/screening` crea un record e avvia il workflow Temporal
`ScreeningWorkflow` sulla task queue dello scraping; il worker esegue la
pipeline (fetch → extract → classify FATF → AMI → pubblicazione SVI →
persistenza) e a fine corsa richiama `POST /api/alerts`.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import Screening as ScreeningModel
from app.schemas import ScreeningOut, ScreeningRequest
from app.temporal_client import get_client

logger = logging.getLogger("api.screening")

router = APIRouter(prefix="/api/screening", tags=["screening"])


@router.post("", response_model=ScreeningOut, status_code=202)
async def start_screening(
    req: ScreeningRequest, session: AsyncSession = Depends(get_session)
) -> ScreeningModel:
    screening = ScreeningModel(
        denominazione=req.denominazione,
        tipo_soggetto=req.tipo_soggetto,
        cf_piva=req.cf_piva,
        cup=req.cup,
        seed_url=req.seed_url,
        status="running",
    )
    session.add(screening)
    await session.commit()
    await session.refresh(screening)

    payload = {
        "screening_id": screening.id,
        "tipo_soggetto": req.tipo_soggetto,
        "denominazione": req.denominazione,
        "nome": req.nome,
        "cognome": req.cognome,
        "data_nascita": req.data_nascita,
        "cf_piva": req.cf_piva,
        "cup": req.cup,
        "seed_url": req.seed_url or "https://example.com",
    }
    try:
        client = await get_client()
        await client.start_workflow(
            "ScreeningWorkflow",
            payload,
            id=f"screening-{screening.id}",
            task_queue=settings.scraping_task_queue,
        )
    except Exception as exc:  # noqa: BLE001 — Temporal non raggiungibile
        screening.status = "failed"
        await session.commit()
        logger.exception("Avvio workflow fallito")
        raise HTTPException(status_code=503, detail=f"orchestratore non disponibile: {exc}") from exc

    return screening


@router.get("/{screening_id}", response_model=ScreeningOut)
async def get_screening(
    screening_id: str, session: AsyncSession = Depends(get_session)
) -> ScreeningModel:
    row = await session.get(ScreeningModel, screening_id)
    if row is None:
        raise HTTPException(status_code=404, detail="screening non trovato")
    return row
