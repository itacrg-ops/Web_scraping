"""Registro dei soggetti noti (anti-omonimia, §8) — persistito su PostgreSQL.

CRUD dalla console (tab "Soggetti"), protetto da `require_user`. L'endpoint
`GET /registry` è **interno** e protetto dal token di servizio (`require_internal`,
header `X-Internal-Token`): lo consuma solo l'entity-resolution per caricare il
registro su cui fare il matching. Contiene dati personali (CF, data e luogo di
nascita delle persone fisiche): non deve mai essere raggiungibile senza token.

Il registro impara dai revisori: nomi simili confermati come varianti dello stesso
soggetto (alias) o come soggetti diversi — usati dall'Entity Resolution — e articoli
confermati a valle dell'etichettatura (`/{id}/articles`). Rinominare un soggetto
conserva il nome precedente come variante; correzioni e decisioni vanno nell'audit.
"""
from __future__ import annotations

import csv
import io

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import User, require_internal, require_user
from app.db import get_session
from app.models import Alert as AlertModel
from app.models import Subject as SubjectModel
from app.models import SubjectArticle, SubjectName
from app.names import SIMILAR_MIN, clean_id, similarity, subject_key
from app.registry_lookup import confirmed_counts, find_duplicate, homonym, merge_roles, subject_out
from app.schemas import (
    NameDecisionIn,
    SimilarCandidate,
    SimilarOut,
    SubjectArticleOut,
    SubjectCreate,
    SubjectImportRequest,
    SubjectImportResult,
    SubjectOut,
    SubjectUpdate,
)

router = APIRouter(prefix="/api/subjects", tags=["subjects"])

_MAX_IMPORT_ROWS = 5000


@router.get("/registry", dependencies=[Depends(require_internal)])
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
            "luogo_nascita": r.luogo_nascita,
            "cup": r.cup or [],
            "ruolo": r.ruolo,
            # decisioni dei revisori sui nomi simili (Entity Resolution)
            "alias": [n.name for n in r.names if n.decision == "stesso"],
            "distinti": [n.name for n in r.names if n.decision == "diverso"],
        }
        for r in rows
    ]
    return {"count": len(items), "subjects": items}


@router.get("", response_model=list[SubjectOut], dependencies=[Depends(require_user)])
async def list_subjects(session: AsyncSession = Depends(get_session)) -> list[dict]:
    stmt = select(SubjectModel).order_by(SubjectModel.tipo_soggetto, SubjectModel.denominazione)
    rows = (await session.execute(stmt)).scalars().all()
    counts = await confirmed_counts(session)
    return [subject_out(r, counts.get(r.id, 0)) for r in rows]


@router.get("/similar", response_model=SimilarOut, dependencies=[Depends(require_user)])
async def similar_subjects(
    tipo_soggetto: str = Query("persona_giuridica"), denominazione: str | None = None,
    nome: str | None = None, cognome: str | None = None, cf_piva: str | None = None,
    data_nascita: str | None = None, session: AsyncSession = Depends(get_session),
) -> SimilarOut:
    """Prima di uno screening (o di aggiungere un soggetto): c'è già lo stesso nome, o un
    nome SIMILE («Stropp» / «Stroppa»), nel registro o tra i soggetti già screenati? I
    nomi che un revisore ha già dichiarato «altro soggetto» non vengono riproposti.

    Con `cf_piva` e `data_nascita` il soggetto «già inserito» segue la regola di
    find_duplicate: stesso CF/P.IVA (anche con un altro nome); lo stesso nome con un
    CF/P.IVA o una data di nascita diversi è un omonimo e compare tra i simili."""
    name = (denominazione or " ".join(p for p in (cognome, nome) if p) or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="indicare la denominazione oppure nome e cognome")
    key = subject_key(name, tipo_soggetto)
    cf = clean_id(cf_piva)

    screened: dict[str, list] = defaultdict(list)   # chiave → nomi degli alert
    for subj_name, in (await session.execute(
        select(AlertModel.subject).where(AlertModel.tipo_soggetto == tipo_soggetto)
    )).all():
        screened[subject_key(subj_name, tipo_soggetto)].append(subj_name)

    exact, exact_cf, similar, registry_keys = None, None, [], set()
    rows = (await session.execute(
        select(SubjectModel).where(SubjectModel.tipo_soggetto == tipo_soggetto))).scalars().all()
    for r in rows:
        rkey = subject_key(r.denominazione, r.tipo_soggetto)
        aliases = [n for n in r.names if n.decision == "stesso"]
        # nome e varianti confermate: gli alert con questi nomi sono dello stesso soggetto
        keys = {rkey} | {n.name_key for n in aliases}
        registry_keys |= keys
        cand = dict(fonte="registro", subject_id=r.id, denominazione=r.denominazione,
                    tipo_soggetto=r.tipo_soggetto, cf_piva=r.cf_piva, data_nascita=r.data_nascita,
                    luogo_nascita=r.luogo_nascita, alert=sum(len(screened.get(k, [])) for k in keys))
        if cf and clean_id(r.cf_piva) == cf:
            exact_cf = exact_cf or SimilarCandidate(**cand, score=1.0)
            continue
        if rkey == key or any(n.name_key == key for n in aliases):
            if homonym(r, cf, data_nascita):       # stesso nome, identificativo diverso: omonimo
                similar.append(SimilarCandidate(**cand, score=1.0))
            else:
                exact = exact or SimilarCandidate(**cand, score=1.0)
            continue
        if any(n.decision == "diverso" and n.name_key == key for n in r.names):
            continue
        score = max([similarity(name, r.denominazione, tipo_soggetto)]
                    + [similarity(name, n.name, tipo_soggetto) for n in aliases])
        if score >= SIMILAR_MIN:
            similar.append(SimilarCandidate(**cand, score=round(score, 3)))
    for skey, names_ in screened.items():
        if skey == key or skey in registry_keys:
            continue
        score = similarity(name, names_[0], tipo_soggetto)
        if score >= SIMILAR_MIN:
            similar.append(SimilarCandidate(fonte="screening", denominazione=names_[-1],
                                            tipo_soggetto=tipo_soggetto, score=round(score, 3),
                                            alert=len(names_)))
    similar.sort(key=lambda c: (-c.score, c.fonte != "registro"))
    return SimilarOut(nome=name, registro_esatto=exact_cf or exact, alert_esistenti=len(screened.get(key, [])),
                      simili=similar[:5])


@router.post("", response_model=SubjectOut, status_code=201)
async def create_subject(
    payload: SubjectCreate, user: User = Depends(require_user), session: AsyncSession = Depends(get_session)
) -> dict:
    """Aggiunge un soggetto; 409 «soggetto già inserito» se c'è già (stesso CF/P.IVA, o
    stesso nome senza un CF/P.IVA o una data di nascita diversi che lo distinguano da un
    omonimo)."""
    dup = await find_duplicate(session, payload.tipo_soggetto, payload.denominazione, payload.cf_piva,
                               payload.data_nascita)
    if dup is not None:
        raise HTTPException(status_code=409, detail=f"Soggetto già inserito nel registro: «{dup.denominazione}»"
                            + (f" (CF/P.IVA {dup.cf_piva})" if dup.cf_piva else ""))
    row = SubjectModel(
        tipo_soggetto=payload.tipo_soggetto,
        denominazione=payload.denominazione,
        cf_piva=payload.cf_piva or None,
        data_nascita=payload.data_nascita or None,
        luogo_nascita=payload.luogo_nascita or None,
        cup=payload.cup,
        ruolo=payload.ruolo or None,
        attivo=payload.attivo,
        pep=payload.pep,
        cariche=merge_roles([], payload.cariche),
        names=[],
    )
    session.add(row)
    await session.flush()
    audit.record(session, user, "subject.create", "subject", row.id)
    await session.commit()
    return subject_out(row)


@router.patch("/{subject_id}", response_model=SubjectOut)
async def update_subject(
    subject_id: str, payload: SubjectUpdate, user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await session.get(SubjectModel, subject_id)
    if row is None:
        raise HTTPException(status_code=404, detail="soggetto non trovato")
    old_name = row.denominazione
    # Applica solo i campi effettivamente inviati (PATCH). Per i campi stringa
    # nullabili, "" significa "azzera".
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "denominazione":
            if not (value and value.strip()):
                raise HTTPException(status_code=400, detail="denominazione non può essere vuota")
            row.denominazione = value.strip()
        elif key in ("cf_piva", "data_nascita", "luogo_nascita", "ruolo", "tipo_soggetto"):
            setattr(row, key, (value or None))
        elif key == "cariche":
            row.cariche = merge_roles([], value or [])
        elif value is not None:  # cup, attivo, pep
            setattr(row, key, value)
    old_key, new_key = subject_key(old_name, row.tipo_soggetto), subject_key(row.denominazione, row.tipo_soggetto)
    if old_key != new_key:
        # Il nome precedente (refuso corretto, vecchia ragione sociale) resta una variante
        # dello stesso soggetto; il nuovo nome non è più "variante" né "altro soggetto".
        for n in [n for n in row.names if n.name_key == new_key]:
            row.names.remove(n)
        if not any(n.name_key == old_key for n in row.names):
            row.names.append(SubjectName(name=old_name, name_key=old_key, decision="stesso",
                                         decided_by=user.sub or user.name, decided_by_name=user.name))
        audit.record(session, user, "subject.rename", "subject", row.id, da=old_name, a=row.denominazione)
    await session.commit()
    counts = await confirmed_counts(session, [row.id])
    return subject_out(row, counts.get(row.id, 0))


@router.post("/{subject_id}/names", response_model=SubjectOut)
async def decide_name(
    subject_id: str, payload: NameDecisionIn, user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Decisione su un nome simile: «stesso» (variante/refuso: l'Entity Resolution lo
    riconoscerà come questo soggetto) o «diverso» (altro soggetto: non riproporlo)."""
    row = await session.get(SubjectModel, subject_id)
    if row is None:
        raise HTTPException(status_code=404, detail="soggetto non trovato")
    key = subject_key(payload.name, row.tipo_soggetto)
    if key == subject_key(row.denominazione, row.tipo_soggetto):
        raise HTTPException(status_code=422, detail="è già il nome del soggetto")
    current = next((n for n in row.names if n.name_key == key), None)
    if current is None:
        current = SubjectName(name_key=key)
        row.names.append(current)
    current.name, current.decision = payload.name.strip(), payload.decision
    current.decided_by, current.decided_by_name = user.sub or user.name, user.name
    current.decided_at = datetime.now(timezone.utc)
    audit.record(session, user, f"subject.name_{payload.decision}", "subject", row.id, nome=payload.name.strip())
    await session.commit()
    counts = await confirmed_counts(session, [row.id])
    return subject_out(row, counts.get(row.id, 0))


@router.delete("/{subject_id}/names/{name_id}", status_code=204)
async def undo_name_decision(subject_id: str, name_id: str, user: User = Depends(require_user),
                             session: AsyncSession = Depends(get_session)):
    row = await session.get(SubjectModel, subject_id)
    current = next((n for n in row.names if n.id == name_id), None) if row else None
    if current is None:
        raise HTTPException(status_code=404, detail="decisione non trovata")
    row.names.remove(current)
    audit.record(session, user, "subject.name_annullato", "subject", row.id, nome=current.name,
                 era=current.decision)
    await session.commit()
    return Response(status_code=204)


@router.get("/{subject_id}/articles", response_model=list[SubjectArticleOut],
            dependencies=[Depends(require_user)])
async def confirmed_articles(subject_id: str, session: AsyncSession = Depends(get_session)) -> list:
    """Notizie confermate dai revisori per il soggetto (storico verificato)."""
    stmt = (select(SubjectArticle).where(SubjectArticle.subject_id == subject_id)
            .order_by(SubjectArticle.confirmed_at.desc()))
    return list((await session.execute(stmt)).scalars().all())


@router.delete("/{subject_id}/articles/{article_id}", status_code=204)
async def remove_confirmed_article(subject_id: str, article_id: str, user: User = Depends(require_user),
                                   session: AsyncSession = Depends(get_session)):
    row = await session.get(SubjectArticle, article_id)
    if row is None or row.subject_id != subject_id:
        raise HTTPException(status_code=404, detail="articolo non trovato")
    await session.delete(row)
    audit.record(session, user, "subject.article_rimosso", "subject", subject_id, url=row.url)
    await session.commit()
    return Response(status_code=204)


@router.post("/import", response_model=SubjectImportResult, dependencies=[Depends(require_user)])
async def import_subjects(
    payload: SubjectImportRequest, session: AsyncSession = Depends(get_session)
) -> SubjectImportResult:
    """Import massivo da CSV. Un soggetto già inserito (stessa regola di find_duplicate)
    viene aggiornato: le celle vuote non cancellano i dati presenti. Non fatale sulle
    righe invalide: le salta e le riporta nel risultato."""
    reader = csv.DictReader(io.StringIO(payload.csv))
    created = updated = 0
    errors: list[str] = []
    # Indice del registro (stessa regola di find_duplicate) costruito una volta: con
    # migliaia di righe non si rilegge il registro a ogni riga.
    by_cf: dict[str, SubjectModel] = {}
    by_key: dict[tuple, list[SubjectModel]] = defaultdict(list)   # nome o variante → soggetti

    def index(r: SubjectModel) -> None:
        if clean_id(r.cf_piva):
            by_cf.setdefault(clean_id(r.cf_piva), r)
        keys = {subject_key(r.denominazione, r.tipo_soggetto)} | {n.name_key for n in r.names
                                                                  if n.decision == "stesso"}
        for k in keys:
            if r not in by_key[(r.tipo_soggetto, k)]:
                by_key[(r.tipo_soggetto, k)].append(r)

    def duplicate_of(sc: SubjectCreate) -> SubjectModel | None:
        cf = clean_id(sc.cf_piva)
        if cf and cf in by_cf:
            return by_cf[cf]
        named = by_key.get((sc.tipo_soggetto, subject_key(sc.denominazione, sc.tipo_soggetto)), [])
        return next((r for r in named if not homonym(r, cf, sc.data_nascita)), None)

    for r in (await session.execute(select(SubjectModel))).scalars().all():
        index(r)
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
                luogo_nascita=row.get("luogo_nascita") or None,
                cf_piva=row.get("cf_piva") or None,
                cup=[c.strip() for c in (row.get("cup") or "").split(";") if c.strip()],
                ruolo=row.get("ruolo") or None,
                pep=(row.get("pep") or "").lower() in ("si", "sì", "s", "true", "1", "x"),
                cariche=[c.strip() for c in (row.get("cariche") or "").split(";") if c.strip()],
            )
        except Exception as exc:  # noqa: BLE001 — riga invalida, non fatale
            errors.append(f"riga {i}: {exc}")
            continue

        # stesso CF/P.IVA, o stesso nome senza CF diverso: si aggiorna, niente doppioni
        existing = duplicate_of(sc)
        if existing is not None:
            existing.tipo_soggetto = sc.tipo_soggetto
            # una riga scritta con una variante confermata non rinomina il soggetto
            row_key = subject_key(sc.denominazione, sc.tipo_soggetto)
            if not any(n.decision == "stesso" and n.name_key == row_key for n in existing.names):
                existing.denominazione = sc.denominazione
            # le celle vuote non cancellano i dati già presenti
            existing.cf_piva = sc.cf_piva or existing.cf_piva
            existing.data_nascita = sc.data_nascita or existing.data_nascita
            existing.luogo_nascita = sc.luogo_nascita or existing.luogo_nascita
            existing.cup = sc.cup or existing.cup
            existing.ruolo = sc.ruolo or existing.ruolo
            existing.pep = existing.pep or sc.pep
            existing.cariche = merge_roles(existing.cariche, sc.cariche)
            existing.attivo = True
            index(existing)  # CF o nome nuovi: le righe successive lo trovano
            updated += 1
        else:
            new_row = SubjectModel(
                tipo_soggetto=sc.tipo_soggetto, denominazione=sc.denominazione,
                cf_piva=sc.cf_piva or None, data_nascita=sc.data_nascita,
                luogo_nascita=sc.luogo_nascita,
                cup=sc.cup, ruolo=sc.ruolo, attivo=True, pep=sc.pep,
                cariche=merge_roles([], sc.cariche), names=[],
            )
            session.add(new_row)
            index(new_row)   # le righe successive lo vedono (niente doppioni nel file)
            created += 1
    await session.commit()
    return SubjectImportResult(created=created, updated=updated, errors=errors[:50])


@router.delete("/{subject_id}", status_code=204)
async def delete_subject(subject_id: str, user: User = Depends(require_user),
                         session: AsyncSession = Depends(get_session)):
    # Nota: niente annotazione di ritorno `-> None` (FastAPI la tratterebbe come
    # response model e va in conflitto con lo status 204 "senza body").
    row = await session.get(SubjectModel, subject_id)
    if row is None:
        raise HTTPException(status_code=404, detail="soggetto non trovato")
    audit.record(session, user, "subject.delete", "subject", row.id)
    await session.delete(row)   # varianti e articoli confermati: ON DELETE CASCADE
    await session.commit()
