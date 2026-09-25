"""Rivalutazione del dataset etichettato, on demand dalla console (pagina Observability).

`POST /api/replay` avvia il workflow Temporal `ReplayWorkflow` sulla task queue dello
scraping: il worker ripassa i casi etichettati nella versione attuale del sistema
(`replay.py`: articoli già salvati, nessuna nuova ricerca), segnala l'avanzamento e
consegna la nuova predizione per caso; l'API calcola il report prima/dopo con la logica
di `app/evaluation.py` (la stessa di `scripts/evaluate_labels.py`).

Il report contiene dati personali (nomi dei soggetti dei casi sbagliati, articoli):
riservato ai ruoli di `DATASET_EXPORT_ROLES`; si tengono solo le ultime rivalutazioni.
Una sola rivalutazione alla volta.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, evaluation
from app.auth import User, check_roles, require_internal, require_user
from app.config import settings
from app.db import get_session
from app.models import ReplayRun
from app.routers.labels import _export_record, _labeled
from app.schemas import ReplayProgress, ReplayResultIn, ReplayRunDetail, ReplayRunOut, ReplayStart
from app.temporal_client import get_client

logger = logging.getLogger("api.replay")

router = APIRouter(prefix="/api/replay", tags=["replay"])

KEEP_RUNS = 20                        # rivalutazioni conservate (minimizzazione)
STALE_AFTER = timedelta(minutes=30)   # «in corso» senza avanzamento da tanto: interrotta


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _rate(w: dict | None) -> float | None:
    return (w or {}).get("rate")


def _summary(run: ReplayRun) -> dict | None:
    """Esito dei casi prima → dopo, per l'elenco delle rivalutazioni."""
    rep = run.report or {}
    if not rep.get("dopo"):
        return None
    pick = {k: [_rate(rep["prima"]["esito"].get(k)), _rate(rep["dopo"]["esito"].get(k))]
            for k in ("accordo", "falsi_negativi", "falsi_positivi")}
    return {"casi": rep["dopo"].get("casi"), **pick,
            "corretti": len(rep.get("cambiamenti", {}).get("corretti", [])),
            "peggiorati": len(rep.get("cambiamenti", {}).get("peggiorati", []))}


def _out(run: ReplayRun, detail: bool = False) -> dict:
    fields = ("id", "status", "solo_affidabili", "started_by_name", "total", "done", "counts", "error",
              "created_at", "updated_at", "finished_at")
    out = {k: getattr(run, k) for k in fields}
    out["sintesi"] = _summary(run)
    if detail:
        out["report"] = run.report
    return out


async def _expire_stale(session: AsyncSession) -> list[ReplayRun]:
    """Le rivalutazioni «in corso» ancora vive; quelle ferme da STALE_AFTER (worker o
    Temporal spariti a metà) diventano fallite."""
    running = list((await session.execute(select(ReplayRun).where(ReplayRun.status == "running"))).scalars())
    alive = []
    for run in running:
        if _now() - _aware(run.updated_at or run.created_at) > STALE_AFTER:
            run.status, run.finished_at = "failed", _now()
            run.error = "interrotta: nessun avanzamento da oltre 30 minuti (worker o Temporal non disponibili)"
        else:
            alive.append(run)
    await session.commit()
    return alive


@router.post("", response_model=ReplayRunOut, status_code=202)
async def start_replay(payload: ReplayStart, user: User = Depends(require_user),
                       session: AsyncSession = Depends(get_session)) -> dict:
    check_roles(user, settings.dataset_export_roles)
    if await _expire_stale(session):
        raise HTTPException(status_code=409, detail="c'è già una rivalutazione in corso")
    run = ReplayRun(status="running", solo_affidabili=payload.solo_affidabili,
                    started_by=user.sub or user.name, started_by_name=user.name)
    session.add(run)
    await session.flush()
    audit.record(session, user, "replay.avvio", "replay_run", run.id, solo_affidabili=payload.solo_affidabili)
    old = list((await session.execute(
        select(ReplayRun.id).order_by(ReplayRun.created_at.desc()).offset(KEEP_RUNS))).scalars())
    if old:
        await session.execute(delete(ReplayRun).where(ReplayRun.id.in_(old)))
    await session.commit()
    try:
        client = await get_client()
        await client.start_workflow(
            "ReplayWorkflow", {"run_id": run.id, "solo_affidabili": payload.solo_affidabili},
            id=f"replay-{run.id}", task_queue=settings.scraping_task_queue,
        )
    except Exception as exc:  # noqa: BLE001 — Temporal non raggiungibile
        run.status, run.finished_at, run.error = "failed", _now(), f"orchestratore non disponibile: {exc}"[:500]
        await session.commit()
        logger.exception("Avvio della rivalutazione fallito")
        raise HTTPException(status_code=503, detail=f"orchestratore non disponibile: {exc}") from exc
    await session.refresh(run)
    return _out(run)


@router.get("", response_model=list[ReplayRunOut])
async def list_replays(user: User = Depends(require_user), session: AsyncSession = Depends(get_session)) -> list:
    check_roles(user, settings.dataset_export_roles)
    await _expire_stale(session)
    rows = (await session.execute(select(ReplayRun).order_by(ReplayRun.created_at.desc()).limit(KEEP_RUNS))).scalars()
    return [_out(r) for r in rows]


@router.get("/{run_id}", response_model=ReplayRunDetail)
async def get_replay(run_id: str, user: User = Depends(require_user),
                     session: AsyncSession = Depends(get_session)) -> dict:
    check_roles(user, settings.dataset_export_roles)
    await _expire_stale(session)
    run = await session.get(ReplayRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="rivalutazione non trovata")
    return _out(run, detail=True)


@router.post("/{run_id}/progress", status_code=204, dependencies=[Depends(require_internal)])
async def replay_progress(run_id: str, payload: ReplayProgress,
                          session: AsyncSession = Depends(get_session)) -> Response:
    """Dal worker, dopo ogni caso: avanzamento (e segno di vita)."""
    run = await session.get(ReplayRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="rivalutazione non trovata")
    if run.status == "running":
        run.done, run.total, run.updated_at = payload.done, payload.total, _now()
        await session.commit()
    return Response(status_code=204)


@router.post("/{run_id}/result", response_model=ReplayRunOut, dependencies=[Depends(require_internal)])
async def replay_result(run_id: str, payload: ReplayResultIn,
                        session: AsyncSession = Depends(get_session)) -> dict:
    """Dal worker, alla fine: la nuova predizione per alert → report prima/dopo sui casi
    rivalutati (con le etichette di adesso). Oppure l'errore che l'ha fermata."""
    run = await session.get(ReplayRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="rivalutazione non trovata")
    if run.status == "completed":          # consegna ripetuta: niente da fare
        return _out(run)
    if payload.status == "failed":
        run.status, run.error = "failed", (payload.error or "errore sconosciuto")[:2000]
    else:
        results = payload.results or {}
        records = [{**_export_record(lab, alert), "replay": results[alert.id]}
                   for lab, alert in await _labeled(session, run.solo_affidabili) if alert.id in results]
        report = evaluation.replay_report(records)
        run.report = json.loads(json.dumps(report, ensure_ascii=False, default=str))
        run.counts = report["rivalutazione"]
        run.status, run.error, run.done = "completed", None, len(results)
        run.total = max(run.total, len(results))
    run.finished_at = _now()
    await session.commit()
    await session.refresh(run)
    return _out(run)
