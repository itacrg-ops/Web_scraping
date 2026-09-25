"""Avvio e stato di uno screening (walking skeleton end-to-end).

`POST /api/screening` crea un record e avvia il workflow Temporal
`ScreeningWorkflow` sulla task queue dello scraping; il worker esegue la
pipeline (fetch → extract → classify FATF → AMI), salva l'alert (`POST
/api/alerts`), lo pubblica in SVI e ne registra l'esito. Se la pipeline fallisce,
il worker chiama `POST /api/screening/{id}/failed` (interno).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import User, require_internal, require_user
from app.config import settings
from app.db import get_session
from app.models import Screening as ScreeningModel
from app.schemas import ScreeningFailure, ScreeningOut, ScreeningRequest
from app.temporal_client import get_client

logger = logging.getLogger("api.screening")

router = APIRouter(prefix="/api/screening", tags=["screening"])


@router.post("", response_model=ScreeningOut, status_code=202)
async def start_screening(
    req: ScreeningRequest, user: User = Depends(require_user), session: AsyncSession = Depends(get_session)
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
    await session.flush()
    if req.subject_id:
        # disambiguazione umana: chi ha indicato l'identità (l'ER la registra come
        # «scelta_revisore» nell'alert)
        audit.record(session, user, "screening.soggetto_indicato", "subject", req.subject_id,
                     screening=screening.id)
    await session.commit()
    await session.refresh(screening)

    payload = {
        "screening_id": screening.id,
        "tipo_soggetto": req.tipo_soggetto,
        "denominazione": req.denominazione,
        "nome": req.nome,
        "cognome": req.cognome,
        "data_nascita": req.data_nascita,
        "luogo_nascita": req.luogo_nascita,
        "cf_piva": req.cf_piva,
        "azienda": req.azienda,
        "localita": req.localita,
        "ruolo": req.ruolo,
        "cup": req.cup,
        "subject_id": req.subject_id or None,
        # Precedenza: seed_url (override) → seed_urls (candidati console) →
        # ricerca automatica nel workflow (se entrambi vuoti).
        "seed_url": req.seed_url or None,
        "seed_urls": req.seed_urls,
        "max_articles": req.max_articles,
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


@router.get("/{screening_id}", response_model=ScreeningOut, dependencies=[Depends(require_user)])
async def get_screening(
    screening_id: str, session: AsyncSession = Depends(get_session)
) -> ScreeningModel:
    row = await session.get(ScreeningModel, screening_id)
    if row is None:
        raise HTTPException(status_code=404, detail="screening non trovato")
    return row


@router.post("/{screening_id}/failed", response_model=ScreeningOut,
             dependencies=[Depends(require_internal)])
async def mark_screening_failed(
    screening_id: str, payload: ScreeningFailure, session: AsyncSession = Depends(get_session)
) -> ScreeningModel:
    """Chiamato dal worker se la pipeline fallisce: lo screening non resta
    "running" per sempre. Vale solo da `running` (uno screening già `completed`,
    cioè con l'alert salvato, non viene retrocesso). Idempotente."""
    row = await session.get(ScreeningModel, screening_id)
    if row is None:
        raise HTTPException(status_code=404, detail="screening non trovato")
    if row.status == "running":
        row.status = "failed"
        row.error = payload.error[:2000]
        await session.commit()
    return row
