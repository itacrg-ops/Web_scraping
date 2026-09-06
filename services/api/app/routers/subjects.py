"""Registro dei soggetti noti (anti-omonimia, §8) — persistito su PostgreSQL.

CRUD dalla console (tab "Soggetti"), protetto da `require_user`. L'endpoint
`GET /registry` è **interno** (senza auth utente): lo consuma l'entity-resolution
per caricare il registro dei soggetti su cui fare il matching.
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_user
from app.db import get_session
from app.models import Subject as SubjectModel
from app.schemas import (
    SubjectCreate,
    SubjectImportRequest,
    SubjectImportResult,
    SubjectOut,
    SubjectUpdate,
)

router = APIRouter(prefix="/api/subjects", tags=["subjects"])

_MAX_IMPORT_ROWS = 5000


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


@router.patch("/{subject_id}", response_model=SubjectOut, dependencies=[Depends(require_user)])
async def update_subject(
    subject_id: str, payload: SubjectUpdate, session: AsyncSession = Depends(get_session)
) -> SubjectModel:
    row = await session.get(SubjectModel, subject_id)
    if row is None:
        raise HTTPException(status_code=404, detail="soggetto non trovato")
    # Applica solo i campi effettivamente inviati (PATCH). Per i campi stringa
    # nullabili, "" significa "azzera".
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "denominazione":
            if not (value and value.strip()):
                raise HTTPException(status_code=400, detail="denominazione non può essere vuota")
            row.denominazione = value.strip()
        elif key in ("cf_piva", "data_nascita", "ruolo", "tipo_soggetto"):
            setattr(row, key, (value or None))
        else:  # cup, attivo
            setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return row


@router.post("/import", response_model=SubjectImportResult, dependencies=[Depends(require_user)])
async def import_subjects(
    payload: SubjectImportRequest, session: AsyncSession = Depends(get_session)
) -> SubjectImportResult:
    """Import massivo da CSV (upsert per CF/P.IVA). Non fatale sulle righe
    invalide: le salta e le riporta nel risultato."""
    reader = csv.DictReader(io.StringIO(payload.csv))
    created = updated = 0
    errors: list[str] = []
    for i, raw in enumerate(reader, start=2):  # riga 1 = header
        if i - 1 > _MAX_IMPORT_ROWS:
            errors.append(f"troppe righe (max {_MAX_IMPORT_ROWS}): resto ignorato")
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            sc = SubjectCreate(
                tipo_soggetto=row.get("tipo_soggetto") or "persona_giuridica",
                denominazione=row.get("denominazione") or None,
                nome=row.get("nome") or None,
                cognome=row.get("cognome") or None,
                data_nascita=row.get("data_nascita") or None,
                cf_piva=row.get("cf_piva") or None,
                cup=[c.strip() for c in (row.get("cup") or "").split(";") if c.strip()],
                ruolo=row.get("ruolo") or None,
            )
        except Exception as exc:  # noqa: BLE001 — riga invalida, non fatale
            errors.append(f"riga {i}: {exc}")
            continue

        existing = None
        if sc.cf_piva:
            existing = (
                await session.execute(select(SubjectModel).where(SubjectModel.cf_piva == sc.cf_piva))
            ).scalars().first()
        if existing is not None:
            existing.tipo_soggetto = sc.tipo_soggetto
            existing.denominazione = sc.denominazione
            existing.data_nascita = sc.data_nascita
            existing.cup = sc.cup
            existing.ruolo = sc.ruolo
            existing.attivo = True
            updated += 1
        else:
            session.add(SubjectModel(
                tipo_soggetto=sc.tipo_soggetto, denominazione=sc.denominazione,
                cf_piva=sc.cf_piva or None, data_nascita=sc.data_nascita,
                cup=sc.cup, ruolo=sc.ruolo, attivo=True,
            ))
            created += 1
    await session.commit()
    return SubjectImportResult(created=created, updated=updated, errors=errors[:50])


@router.delete("/{subject_id}", status_code=204, dependencies=[Depends(require_user)])
async def delete_subject(subject_id: str, session: AsyncSession = Depends(get_session)):
    # Nota: niente annotazione di ritorno `-> None` (FastAPI la tratterebbe come
    # response model e va in conflitto con lo status 204 "senza body").
    row = await session.get(SubjectModel, subject_id)
    if row is None:
        raise HTTPException(status_code=404, detail="soggetto non trovato")
    await session.delete(row)
    await session.commit()
