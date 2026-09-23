"""Collegamento tra alert, nomi e registro dei soggetti (anti-omonimia).

Usato dalla scheda del caso (casi dello stesso soggetto, articoli già confermati),
dal controllo dei nomi simili prima di uno screening e dalla conferma degli articoli
nel registro. Scansioni in memoria: adeguate al registro del pilota (migliaia di
soggetti); con registri molto grandi servirebbe un indice trigram in Postgres.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert as AlertModel
from app.models import Subject as SubjectModel
from app.models import SubjectArticle
from app.names import clean_id, subject_key


def same_subject(a_name: str, a_tipo: str | None, a_cf: str | None,
                 b_name: str, b_tipo: str | None, b_cf: str | None) -> bool:
    """Stesso soggetto: stesso CF/P.IVA, oppure stesso tipo e stesso nome normalizzato."""
    ca, cb = clean_id(a_cf), clean_id(b_cf)
    if ca and cb:
        return ca == cb
    return (a_tipo or "persona_giuridica") == (b_tipo or "persona_giuridica") \
        and subject_key(a_name, a_tipo) == subject_key(b_name, b_tipo)


async def subject_for_alert(session: AsyncSession, alert: AlertModel) -> tuple[SubjectModel, str] | None:
    """Il soggetto del registro a cui si riferisce l'alert, e come lo si è trovato:
    identità risolta dall'Entity Resolution, CF/P.IVA, nome o variante confermata."""
    matched = (alert.entity_resolution or {}).get("matched") or {}
    if matched.get("id"):
        row = await session.get(SubjectModel, matched["id"])
        if row is not None:
            return row, "entity_resolution"
    cf = clean_id(alert.cf_piva)
    if cf:
        stmt = select(SubjectModel).where(func.upper(func.replace(SubjectModel.cf_piva, " ", "")) == cf)
        row = (await session.execute(stmt)).scalars().first()
        if row is not None:
            return row, "cf_piva"
    return await subject_by_name(session, alert.subject, alert.tipo_soggetto)


async def subject_by_name(session: AsyncSession, name: str, tipo: str | None) -> tuple[SubjectModel, str] | None:
    key = subject_key(name, tipo)
    stmt = select(SubjectModel).where(SubjectModel.tipo_soggetto == (tipo or "persona_giuridica"))
    rows = (await session.execute(stmt)).scalars().all()
    for r in rows:
        if subject_key(r.denominazione, r.tipo_soggetto) == key:
            return r, "nome"
    for r in rows:
        if any(n.decision == "stesso" and n.name_key == key for n in r.names):
            return r, "alias"
    return None


async def confirmed_counts(session: AsyncSession, ids: list[str] | None = None) -> dict[str, int]:
    stmt = select(SubjectArticle.subject_id, func.count()).group_by(SubjectArticle.subject_id)
    if ids is not None:
        stmt = stmt.where(SubjectArticle.subject_id.in_(ids))
    return {sid: n for sid, n in (await session.execute(stmt)).all()}


def subject_out(row: SubjectModel, confirmed: int = 0) -> dict:
    """SubjectOut con le varianti decise dai revisori e il numero di notizie confermate."""
    return {
        "id": row.id, "tipo_soggetto": row.tipo_soggetto, "denominazione": row.denominazione,
        "cf_piva": row.cf_piva, "data_nascita": row.data_nascita, "luogo_nascita": row.luogo_nascita,
        "cup": row.cup or [], "ruolo": row.ruolo, "attivo": row.attivo, "created_at": row.created_at,
        "alias": [n.name for n in row.names if n.decision == "stesso"],
        "distinti": [n.name for n in row.names if n.decision == "diverso"],
        "articoli_confermati": confirmed,
    }
