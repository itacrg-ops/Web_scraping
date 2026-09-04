"""Alert — persistiti su PostgreSQL.

Vista di sintesi/monitoraggio per gli amministratori. La lavorazione
investigativa (triage, dossier, network analysis, disposizione) avviene in
SAS Visual Investigator. La `POST` è interna: la chiama il worker a fine
pipeline per persistere l'esito.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Alert as AlertModel
from app.models import Screening as ScreeningModel
from app.schemas import Alert, AlertCreate

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[Alert])
async def list_alerts(session: AsyncSession = Depends(get_session)) -> list[AlertModel]:
    rows = (
        await session.execute(select(AlertModel).order_by(AlertModel.created_at.desc()))
    ).scalars().all()
    return list(rows)


@router.post("", response_model=Alert, status_code=201)
async def create_alert(payload: AlertCreate, session: AsyncSession = Depends(get_session)) -> AlertModel:
    alert = AlertModel(**payload.model_dump())
    session.add(alert)
    # collega lo screening e marcalo completato
    if payload.screening_id:
        screening = await session.get(ScreeningModel, payload.screening_id)
        if screening is not None:
            screening.status = "completed"
            screening.alert_id = alert.id
    await session.commit()
    await session.refresh(alert)
    return alert
