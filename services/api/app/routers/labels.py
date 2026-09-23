"""Etichette dei casi — dataset di valutazione della qualità del sistema.

I revisori giudicano i casi (alert) dalla console: per ogni articolo se riguarda
davvero il soggetto e se è avverso; per il caso le categorie FATF corrette, il ruolo
del soggetto e la disposition attesa. I casi marcati **affidabili** formano il dataset
con cui misurare precisione e richiamo del sistema (`scripts/evaluate_labels.py`).

Contiene dati personali (anche giudiziari, art. 10 GDPR): l'export in blocco è
riservato ai ruoli di `DATASET_EXPORT_ROLES` e omette gli identificativi non necessari
alla valutazione (CF/P.IVA).
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import User, check_roles, require_user
from app.config import settings
from app.db import get_session
from app.models import Alert as AlertModel
from app.models import CaseLabel
from app.schemas import CaseLabelIn, CaseLabelOut, CaseLabelSummary, LabelStats

router = APIRouter(prefix="/api", tags=["labels"])


def _reviewer(user: User) -> str:
    return user.sub or user.name


async def _alert(session: AsyncSession, alert_id: str) -> AlertModel:
    stmt = select(AlertModel).options(selectinload(AlertModel.evidence)).where(AlertModel.id == alert_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="alert non trovato")
    return row


async def _own_label(session: AsyncSession, alert_id: str, reviewer: str) -> CaseLabel | None:
    stmt = select(CaseLabel).where(CaseLabel.alert_id == alert_id, CaseLabel.reviewer == reviewer)
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("/alerts/{alert_id}/label", response_model=CaseLabelOut | None)
async def get_label(alert_id: str, user: User = Depends(require_user),
                    session: AsyncSession = Depends(get_session)) -> CaseLabel | None:
    """Etichetta del revisore corrente su questo caso (null se non ancora etichettato)."""
    await _alert(session, alert_id)
    return await _own_label(session, alert_id, _reviewer(user))


@router.put("/alerts/{alert_id}/label", response_model=CaseLabelOut)
async def put_label(alert_id: str, payload: CaseLabelIn, user: User = Depends(require_user),
                    session: AsyncSession = Depends(get_session)) -> CaseLabel:
    """Crea o aggiorna l'etichetta del revisore corrente. Un caso `affidabile` deve
    avere un giudizio completo e senza "incerto", altrimenti 422 con cosa manca."""
    alert = await _alert(session, alert_id)
    evidence_ids = [e.id for e in alert.evidence]
    unknown = sorted(set(payload.evidence_labels) - set(evidence_ids))
    if unknown:
        raise HTTPException(status_code=422, detail=f"evidenze non appartenenti all'alert: {unknown}")
    if payload.affidabile and (missing := payload.missing_for_reliable(evidence_ids)):
        raise HTTPException(status_code=422, detail="per includere il caso nel dataset manca: "
                            + "; ".join(missing))

    data = payload.model_dump()
    reviewer = _reviewer(user)
    for attempt in range(2):  # 2° giro solo se un salvataggio concorrente ha già creato la riga
        row = await _own_label(session, alert_id, reviewer)
        if row is None:
            row = CaseLabel(alert_id=alert_id, reviewer=reviewer, reviewer_name=user.name, **data)
            session.add(row)
        else:
            for key, value in data.items():
                setattr(row, key, value)
            row.reviewer_name = user.name
        try:
            await session.commit()
            break
        except IntegrityError:
            await session.rollback()
            if attempt:
                raise
    await session.refresh(row)
    return row


@router.delete("/alerts/{alert_id}/label", status_code=204)
async def delete_label(alert_id: str, user: User = Depends(require_user),
                       session: AsyncSession = Depends(get_session)) -> Response:
    row = await _own_label(session, alert_id, _reviewer(user))
    if row is not None:
        await session.delete(row)
        await session.commit()
    return Response(status_code=204)


@router.get("/labels", response_model=list[CaseLabelSummary])
async def my_labels(user: User = Depends(require_user),
                    session: AsyncSession = Depends(get_session)) -> list[CaseLabel]:
    """Casi già etichettati dal revisore corrente (per marcarli nella lista)."""
    stmt = select(CaseLabel).where(CaseLabel.reviewer == _reviewer(user))
    return list((await session.execute(stmt)).scalars().all())


@router.get("/labels/stats", response_model=LabelStats, dependencies=[Depends(require_user)])
async def label_stats(session: AsyncSession = Depends(get_session)) -> LabelStats:
    """Avanzamento del dataset (tutti i revisori), anche per disposition PREDETTA:
    mostra se si stanno etichettando solo le escalation (bias di selezione)."""
    rows = (await session.execute(
        select(CaseLabel.alert_id, CaseLabel.affidabile, CaseLabel.reviewer, AlertModel.disposition)
        .join(AlertModel, AlertModel.id == CaseLabel.alert_id)
    )).all()
    cases: dict[str, tuple[str, bool]] = {}
    for alert_id, affidabile, _reviewer_id, disposition in rows:
        prev = cases.get(alert_id, (disposition, False))
        cases[alert_id] = (disposition, prev[1] or affidabile)
    return LabelStats(
        etichettati=len(cases),
        affidabili=sum(1 for _, aff in cases.values() if aff),
        revisori=len({r[2] for r in rows}),
        per_disposition=dict(Counter(d for d, _ in cases.values())),
        affidabili_per_disposition=dict(Counter(d for d, aff in cases.values() if aff)),
    )


def _export_record(label: CaseLabel, alert: AlertModel) -> dict:
    ev_labels = label.evidence_labels or {}
    return {
        "schema": "ams-case-label/1",
        "label": {
            "id": label.id, "reviewer": label.reviewer, "affidabile": label.affidabile,
            "categorie_corrette": label.categorie_corrette or [], "ruolo": label.ruolo,
            "disposition_attesa": label.disposition_attesa, "note": label.note,
            "created_at": label.created_at, "updated_at": label.updated_at,
        },
        "alert": {  # predizione del sistema (senza CF/P.IVA: non serve alla valutazione)
            "id": alert.id, "screening_id": alert.screening_id, "subject": alert.subject,
            "tipo_soggetto": alert.tipo_soggetto, "cup": alert.cup or [],
            "ami_score": alert.ami_score, "risk_level": alert.risk_level,
            "disposition": alert.disposition, "fatf_categories": alert.fatf_categories or [],
            "classification": alert.classification, "drivers": alert.drivers or [],
            "created_at": alert.created_at,
        },
        "evidence": [
            {"id": e.id, "url": e.url, "testata": e.testata, "title": e.title, "data": e.data,
             "snippet": e.snippet, "content_hash": e.content_hash, "fetch_ts": e.fetch_ts,
             "warc_key": e.warc_key, "fonte_credibilita": e.fonte_credibilita,
             "mentioned": e.mentioned, "mention_match": e.mention_match,
             "label": ev_labels.get(e.id)}
            for e in alert.evidence
        ],
    }


@router.get("/labels/export")
async def export_labels(solo_affidabili: bool = Query(True), user: User = Depends(require_user),
                        session: AsyncSession = Depends(get_session)) -> Response:
    """Dataset in NDJSON (una riga per etichetta): giudizio del revisore + predizione
    del sistema su caso e articoli. Riservato a DATASET_EXPORT_ROLES."""
    check_roles(user, settings.dataset_export_roles)
    stmt = select(CaseLabel).order_by(CaseLabel.created_at)
    if solo_affidabili:
        stmt = stmt.where(CaseLabel.affidabile.is_(True))
    labels = list((await session.execute(stmt)).scalars().all())
    ids = {lab.alert_id for lab in labels}
    alerts = {a.id: a for a in (await session.execute(
        select(AlertModel).options(selectinload(AlertModel.evidence)).where(AlertModel.id.in_(ids))
    )).scalars().all()} if ids else {}
    lines = [json.dumps(_export_record(lab, alerts[lab.alert_id]), ensure_ascii=False, default=str)
             for lab in labels]
    return Response(
        content="".join(line + "\n" for line in lines),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="dataset-casi-{date.today():%Y%m%d}.ndjson"'},
    )
