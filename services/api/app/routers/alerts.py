"""Alert (con evidenze ancorate) — persistiti su PostgreSQL.

Vista di sintesi/monitoraggio per gli amministratori. La lavorazione
investigativa (triage, dossier, network analysis, disposizione) avviene in
SAS Visual Investigator. La `POST` è interna: la chiama il worker a fine
pipeline per persistere l'esito e le evidenze raccolte.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models import Alert as AlertModel
from app.models import Evidence as EvidenceModel
from app.models import Screening as ScreeningModel
from app.schemas import Alert, AlertCreate

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[Alert])
async def list_alerts(session: AsyncSession = Depends(get_session)) -> list[AlertModel]:
    stmt = (
        select(AlertModel)
        .options(selectinload(AlertModel.evidence))
        .order_by(AlertModel.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{alert_id}", response_model=Alert)
async def get_alert(alert_id: str, session: AsyncSession = Depends(get_session)) -> AlertModel:
    stmt = select(AlertModel).options(selectinload(AlertModel.evidence)).where(AlertModel.id == alert_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="alert non trovato")
    return row


@router.post("", response_model=Alert, status_code=201)
async def create_alert(payload: AlertCreate, session: AsyncSession = Depends(get_session)) -> AlertModel:
    data = payload.model_dump()
    evidence_items = data.pop("evidence", [])

    alert = AlertModel(**data)
    session.add(alert)
    await session.flush()  # assegna alert.id

    for ev in evidence_items:
        session.add(EvidenceModel(alert_id=alert.id, **ev))

    if payload.screening_id:
        screening = await session.get(ScreeningModel, payload.screening_id)
        if screening is not None:
            screening.status = "completed"
            screening.alert_id = alert.id

    await session.commit()

    stmt = select(AlertModel).options(selectinload(AlertModel.evidence)).where(AlertModel.id == alert.id)
    return (await session.execute(stmt)).scalar_one()
