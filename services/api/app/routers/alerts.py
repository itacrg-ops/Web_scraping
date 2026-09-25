"""Alert (con evidenze ancorate) — persistiti su PostgreSQL.

Vista di sintesi/monitoraggio per gli amministratori. La lavorazione
investigativa (triage, dossier, network analysis, disposizione) avviene in
SAS Visual Investigator. Le scritture sono interne (token di servizio): il worker
salva l'alert con le evidenze **prima** di pubblicarlo in SVI (`POST`, idempotente
per screening) e ne registra poi l'esito di pubblicazione (`PATCH …/svi`).

Dalla console: cancellazione di alert duplicati o errati (ruoli `ALERT_DELETE_ROLES`,
con motivo, nell'audit), casi collegati per l'etichettatura (stesso soggetto già nel
dataset, articoli già giudicati o confermati) e conferma degli articoli nel registro.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import audit
from app.auth import User, check_roles, require_internal, require_user
from app.config import settings
from app.db import get_session
from app.models import Alert as AlertModel
from app.models import CaseLabel
from app.models import Evidence as EvidenceModel
from app.models import Screening as ScreeningModel
from app.models import Subject as SubjectModel
from app.models import SubjectArticle, SubjectName
from app.names import subject_key
from app.registry_lookup import (
    confirmed_counts,
    find_duplicate,
    merge_roles,
    same_subject,
    subject_for_alert,
    subject_out,
)
from app.schemas import (
    Alert,
    AlertCreate,
    AlertDeleteRequest,
    AlertDeleteResult,
    AlertSviUpdate,
    ConfirmIn,
    ConfirmOut,
    PriorJudgment,
    RegistryArticle,
    RegistryLink,
    RelatedCase,
    RelatedOut,
)

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


def _reviewer(user: User) -> str:
    return user.sub or user.name


@router.post("/delete", response_model=AlertDeleteResult)
async def delete_alerts(payload: AlertDeleteRequest, user: User = Depends(require_user),
                        session: AsyncSession = Depends(get_session)) -> AlertDeleteResult:
    """Elimina alert duplicati o errati con articoli ed etichette (anche dal dataset).
    Ogni cancellazione va nell'audit con il motivo. Gli alert già pubblicati restano in
    SAS VI: la risposta li elenca, vanno chiusi là."""
    check_roles(user, settings.alert_delete_roles)
    rows = (await session.execute(
        select(AlertModel).options(selectinload(AlertModel.evidence)).where(AlertModel.id.in_(payload.ids))
    )).scalars().all()
    labels = (await session.execute(
        select(CaseLabel.alert_id, CaseLabel.affidabile).where(CaseLabel.alert_id.in_([r.id for r in rows]))
    )).all()
    per_alert: dict[str, list[bool]] = defaultdict(list)
    for aid, aff in labels:
        per_alert[aid].append(bool(aff))
    in_svi = []
    for r in rows:
        audit.record(session, user, "alert.delete", "alert", r.id, motivo=payload.motivo, nota=payload.nota,
                     screening_id=r.screening_id, svi_alert_id=r.svi_alert_id, svi_status=r.svi_status,
                     articoli=len(r.evidence), etichette=len(per_alert[r.id]),
                     affidabili=sum(per_alert[r.id]))
        if r.svi_status == "published" and r.svi_alert_id:
            in_svi.append({"id": r.id, "svi_alert_id": r.svi_alert_id})
        if r.screening_id:
            screening = await session.get(ScreeningModel, r.screening_id)
            if screening is not None and screening.alert_id == r.id:
                screening.alert_id = None
        await session.delete(r)   # articoli via ORM, etichette via ON DELETE CASCADE
    await session.commit()
    return AlertDeleteResult(eliminati=len(rows), etichette_eliminate=len(labels), in_svi=in_svi)


@router.get("/{alert_id}/related", response_model=RelatedOut)
async def related_cases(alert_id: str, user: User = Depends(require_user),
                        session: AsyncSession = Depends(get_session)) -> RelatedOut:
    """Per l'etichettatura: altri casi dello STESSO soggetto (e se sono già nel dataset),
    i giudizi che il revisore ha già dato sugli stessi articoli in quei casi (solo i
    suoi: l'etichettatura resta cieca rispetto agli altri revisori) e gli articoli già
    confermati nel registro per il soggetto."""
    alert = await _load(session, AlertModel.id == alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert non trovato")
    candidates = (await session.execute(
        select(AlertModel.id, AlertModel.subject, AlertModel.tipo_soggetto, AlertModel.cf_piva,
               AlertModel.created_at, AlertModel.disposition).where(AlertModel.id != alert_id)
    )).all()
    same = [c for c in candidates
            if same_subject(alert.subject, alert.tipo_soggetto, alert.cf_piva, c.subject, c.tipo_soggetto, c.cf_piva)]
    same_ids = [c.id for c in same]
    labels = (await session.execute(select(CaseLabel).where(CaseLabel.alert_id.in_(same_ids)))).scalars().all() \
        if same_ids else []
    me = _reviewer(user)
    by_alert: dict[str, list[CaseLabel]] = defaultdict(list)
    for lab in labels:
        by_alert[lab.alert_id].append(lab)
    cases = []
    for c in sorted(same, key=lambda c: c.created_at, reverse=True):
        mine = next((lab for lab in by_alert[c.id] if lab.reviewer == me), None)
        cases.append(RelatedCase(id=c.id, subject=c.subject, created_at=c.created_at, disposition=c.disposition,
                                 etichette=len(by_alert[c.id]), affidabili=sum(lab.affidabile for lab in by_alert[c.id]),
                                 mia=None if mine is None else ("affidabile" if mine.affidabile else "bozza")))

    # I miei giudizi sugli stessi articoli (stesso URL o stesso contenuto) negli altri casi.
    prior: dict[str, list[PriorJudgment]] = {}
    my_labels = {lab.alert_id: lab for lab in labels if lab.reviewer == me}
    if my_labels:
        others = (await session.execute(
            select(EvidenceModel).where(EvidenceModel.alert_id.in_(list(my_labels)))
        )).scalars().all()
        created = {c.id: c.created_at for c in same}
        for e in alert.evidence:
            for o in others:
                if (e.url and o.url == e.url) or (e.content_hash and o.content_hash == e.content_hash):
                    j = (my_labels[o.alert_id].evidence_labels or {}).get(o.id) or {}
                    if j.get("pertinenza") or j.get("avversa"):
                        prior.setdefault(e.id, []).append(PriorJudgment(
                            alert_id=o.alert_id, created_at=created[o.alert_id],
                            pertinenza=j.get("pertinenza"), avversa=j.get("avversa")))

    registry = None
    found = await subject_for_alert(session, alert)
    if found is not None:
        subj, how = found
        confirmed = (await session.execute(
            select(SubjectArticle).where(SubjectArticle.subject_id == subj.id)
        )).scalars().all()
        by_url = {a.url: a for a in confirmed}
        registry = RegistryLink(subject_id=subj.id, denominazione=subj.denominazione, come=how, articoli={
            e.id: RegistryArticle(pertinenza=by_url[e.url].pertinenza, avversa=by_url[e.url].avversa,
                                  confirmed_by_name=by_url[e.url].confirmed_by_name,
                                  confirmed_at=by_url[e.url].confirmed_at)
            for e in alert.evidence if e.url in by_url})
    return RelatedOut(stesso_soggetto=cases, giudizi_precedenti=prior, registro=registry)


_CERTAIN = {"pertinenza": ("si", "omonimo", "non_citato"), "avversa": ("si", "no")}


@router.post("/{alert_id}/confirm", response_model=ConfirmOut)
async def confirm_in_registry(alert_id: str, payload: ConfirmIn, user: User = Depends(require_user),
                              session: AsyncSession = Depends(get_session)) -> ConfirmOut:
    """Conferma nel registro, a valle dell'etichettatura, gli articoli del caso con il
    giudizio del revisore (solo quelli con risposte certe) e il giudizio sul caso. Se il
    nome dell'alert è diverso da quello del soggetto (es. un refuso), lo registra come
    sua variante: l'Entity Resolution lo riconoscerà la prossima volta."""
    alert = await _load(session, AlertModel.id == alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert non trovato")
    label = (await session.execute(select(CaseLabel).where(
        CaseLabel.alert_id == alert_id, CaseLabel.reviewer == _reviewer(user)))).scalar_one_or_none()
    if label is None:
        raise HTTPException(status_code=409, detail="salva prima l'etichetta del caso")
    judged = [(e, (label.evidence_labels or {}).get(e.id) or {}) for e in alert.evidence if e.url]
    certain = [(e, j) for e, j in judged
               if j.get("pertinenza") in _CERTAIN["pertinenza"] and j.get("avversa") in _CERTAIN["avversa"]]
    if not certain:
        raise HTTPException(status_code=422, detail="nessun articolo con giudizio certo da confermare "
                                                    "(servono entrambe le risposte, senza «Incerto»)")

    if payload.subject_id:
        subj = await session.get(SubjectModel, payload.subject_id)
        if subj is None:
            raise HTTPException(status_code=404, detail="soggetto del registro non trovato")
    else:
        new = payload.nuovo
        existing = await find_duplicate(session, new.tipo_soggetto, new.denominazione, new.cf_piva,
                                        new.data_nascita)
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Soggetto già inserito nel registro: "
                                                        f"«{existing.denominazione}». Conferma su quel soggetto.")
        subj = SubjectModel(tipo_soggetto=new.tipo_soggetto, denominazione=new.denominazione.strip(),
                            cf_piva=new.cf_piva or None, data_nascita=new.data_nascita or None,
                            luogo_nascita=new.luogo_nascita or None, cup=new.cup, ruolo=new.ruolo or None,
                            attivo=new.attivo, pep=new.pep, cariche=merge_roles([], new.cariche), names=[])
        session.add(subj)
        await session.flush()
        audit.record(session, user, "subject.create", "subject", subj.id, da_alert=alert.id)
    # ruoli dagli articoli e flag PEP confermati dal revisore
    subj.cariche = merge_roles(subj.cariche, payload.cariche)
    if payload.pep:
        subj.pep = True

    existing_articles = {a.url: a for a in (await session.execute(
        select(SubjectArticle).where(SubjectArticle.subject_id == subj.id))).scalars().all()}
    now = datetime.now(timezone.utc)
    for e, j in certain:   # nuovo articolo o nuova conferma dello stesso URL (vince l'ultima)
        row = existing_articles.get(e.url)
        if row is None:
            row = SubjectArticle(subject_id=subj.id, url=e.url)
            session.add(row)
        row.alert_id, row.testata, row.title, row.data, row.content_hash = \
            alert.id, e.testata, e.title, e.data, e.content_hash
        row.pertinenza, row.avversa = j["pertinenza"], j["avversa"]
        row.categorie, row.ruolo, row.esito = label.categorie_corrette or [], label.ruolo, label.disposition_attesa
        row.confirmed_by, row.confirmed_by_name, row.confirmed_at = _reviewer(user), user.name, now

    alias = None
    key = subject_key(alert.subject, alert.tipo_soggetto)
    known = {subject_key(subj.denominazione, subj.tipo_soggetto)} | {n.name_key for n in subj.names}
    if key not in known:
        subj.names.append(SubjectName(name=alert.subject, name_key=key, decision="stesso",
                                      decided_by=_reviewer(user), decided_by_name=user.name))
        alias = alert.subject
    saltati = len(alert.evidence) - len(certain)
    audit.record(session, user, "subject.confirm_articles", "subject", subj.id, alert_id=alert.id,
                 articoli=len(certain), saltati=saltati, alias=alias, cariche=len(payload.cariche),
                 pep=bool(payload.pep))
    await session.commit()
    counts = await confirmed_counts(session, [subj.id])
    return ConfirmOut(subject=subject_out(subj, counts.get(subj.id, 0)), nuovo_soggetto=not payload.subject_id,
                      confermati=len(certain), saltati=saltati, alias_aggiunto=alias)

