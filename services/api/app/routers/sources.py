"""Registro fonti (§5.1) — persistito su PostgreSQL."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Source as SourceModel
from app.schemas import Source

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[Source])
async def list_sources(session: AsyncSession = Depends(get_session)) -> list[SourceModel]:
    rows = (await session.execute(select(SourceModel).order_by(SourceModel.nome))).scalars().all()
    return list(rows)


@router.get("/{source_id}", response_model=Source)
async def get_source(source_id: str, session: AsyncSession = Depends(get_session)) -> SourceModel:
    row = await session.get(SourceModel, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="fonte non trovata")
    return row


@router.put("/{source_id}", response_model=Source)
async def upsert_source(
    source_id: str, source: Source, session: AsyncSession = Depends(get_session)
) -> SourceModel:
    row = await session.get(SourceModel, source_id)
    data = source.model_dump()
    data["id"] = source_id
    if row is None:
        row = SourceModel(**data)
        session.add(row)
    else:
        for k, v in data.items():
            setattr(row, k, v)
    await session.commit()
    await session.refresh(row)
    return row
