"""Alert (con evidenze ancorate) — persistiti su PostgreSQL.

Vista di sintesi/monitoraggio per gli amministratori. La lavorazione
investigativa (triage, dossier, network analysis, disposizione) avviene in
SAS Visual Investigator. Le scritture sono interne (token di servizio): il worker
salva l'alert con le evidenze **prima** di pubblicarlo in SVI (`POST`, idempotente
per screening) e ne registra poi l'esito di pubblicazione (`PATCH …/svi`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_internal, require_user
from app.db import get_session
from app.models import Alert as AlertModel
from app.models import Evidence as EvidenceModel
from app.models import Screening as ScreeningModel
from app.schemas import Alert, AlertCreate, AlertSviUpdate

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


async def _load(session: AsyncSession, *where) -> AlertModel | None:
    stmt = select(AlertModel).options(selectinload(AlertModel.evidence)).where(*where)
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("", response_model=list[Alert], dependencies=[Depends(require_user)])
async def list_alerts(session: AsyncSession = Depends(get_session)) -> list[AlertModel]:
    stmt = (
        select(AlertModel)
        .options(selectinload(AlertModel.evidence))
        .order_by(AlertModel.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{alert_id}", response_model=Alert, dependencies=[Depends(require_user)])
async def get_alert(alert_id: str, session: AsyncSession = Depends(get_session)) -> AlertModel:
    row = await _load(session, AlertModel.id == alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="alert non trovato")
    return row


@router.post("", response_model=Alert, status_code=201, dependencies=[Depends(require_internal)])
async def create_alert(payload: AlertCreate, response: Response,
                       session: AsyncSession = Depends(get_session)) -> AlertModel:
    """Crea l'alert dello screening. **Idempotente per `screening_id`**: se esiste
    già (retry del worker dopo un timeout) restituisce quello esistente (200)
    invece di duplicarlo."""
    if payload.screening_id:
        existing = await _load(session, AlertModel.screening_id == payload.screening_id)
        if existing is not None:
            response.status_code = 200
            return existing

    data = payload.model_dump()
    evidence_items = data.pop("evidence", [])

    alert = AlertModel(**data)
    session.add(alert)
    try:
        await session.flush()  # assegna alert.id (e fa scattare il vincolo unique)
        for ev in evidence_items:
            session.add(EvidenceModel(alert_id=alert.id, **ev))

        if payload.screening_id:
            screening = await session.get(ScreeningModel, payload.screening_id)
            if screening is not None:
                screening.status = "completed"
                screening.error = None
                screening.alert_id = alert.id

        await session.commit()
    except IntegrityError:
        # Due richieste concorrenti per lo stesso screening: vince la prima.
        await session.rollback()
        existing = await _load(session, AlertModel.screening_id == payload.screening_id) \
            if payload.screening_id else None
        if existing is None:
            raise
        response.status_code = 200
        return existing

    return await _load(session, AlertModel.id == alert.id)


@router.patch("/{alert_id}/svi", response_model=Alert, dependencies=[Depends(require_internal)])
async def update_alert_svi(alert_id: str, payload: AlertSviUpdate,
                           session: AsyncSession = Depends(get_session)) -> AlertModel:
    """Registra l'esito della pubblicazione in SVI (published/failed/…)."""
    row = await _load(session, AlertModel.id == alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="alert non trovato")
    row.svi_status = payload.svi_status
    row.svi_error = payload.svi_error[:2000] if payload.svi_error else None
    if payload.svi_alert_id:
        row.svi_alert_id = payload.svi_alert_id
    await session.commit()
    return await _load(session, AlertModel.id == alert_id)
