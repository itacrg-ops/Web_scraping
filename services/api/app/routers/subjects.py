"""Registro dei soggetti noti (anti-omonimia, §8) — persistito su PostgreSQL.

CRUD dalla console (tab "Soggetti"), protetto da `require_user`. L'endpoint
`GET /registry` è **interno** (senza auth utente): lo consuma l'entity-resolution
per caricare il registro dei soggetti su cui fare il matching.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_user
from app.db import get_session
from app.models import Subject as SubjectModel
from app.schemas import SubjectCreate, SubjectOut

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


@router.get("/registry")
async def registry(session: AsyncSession = Depends(get_session)) -> dict:
    """Registro (soli soggetti attivi) nella forma attesa dall'entity-resolution."""
    stmt = select(SubjectModel).where(SubjectModel.attivo.is_(True))
    rows = (await session.execute(stmt)).scalars().all()
    items = [
        {
            "id": r.id,
            "tipo": r.tipo_soggetto,
            "denominazione": r.denominazione,
            "cf_piva": r.cf_piva,
            "data_nascita": r.data_nascita,
            "cup": r.cup or [],
            "ruolo": r.ruolo,
        }
        for r in rows
    ]
    return {"count": len(items), "subjects": items}


@router.get("", response_model=list[SubjectOut], dependencies=[Depends(require_user)])
async def list_subjects(session: AsyncSession = Depends(get_session)) -> list[SubjectModel]:
    stmt = select(SubjectModel).order_by(SubjectModel.tipo_soggetto, SubjectModel.denominazione)
    return list((await session.execute(stmt)).scalars().all())


@router.post("", response_model=SubjectOut, status_code=201, dependencies=[Depends(require_user)])
async def create_subject(
    payload: SubjectCreate, session: AsyncSession = Depends(get_session)
) -> SubjectModel:
    row = SubjectModel(
        tipo_soggetto=payload.tipo_soggetto,
        denominazione=payload.denominazione,
        cf_piva=payload.cf_piva or None,
        data_nascita=payload.data_nascita or None,
        cup=payload.cup,
        ruolo=payload.ruolo or None,
        attivo=payload.attivo,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/{subject_id}", status_code=204, dependencies=[Depends(require_user)])
async def delete_subject(subject_id: str, session: AsyncSession = Depends(get_session)) -> None:
    row = await session.get(SubjectModel, subject_id)
    if row is None:
        raise HTTPException(status_code=404, detail="soggetto non trovato")
    await session.delete(row)
    await session.commit()
