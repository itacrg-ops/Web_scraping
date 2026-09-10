"""Persistenza: engine async + migrazioni Alembic + seed.

Postgres è il **sistema di record**. Lo schema è gestito con **Alembic**
(`alembic/versions`). All'avvio:
- DB nuovo → `alembic upgrade head` crea lo schema;
- DB preesistente creato in passato con `create_all` (senza `alembic_version`)
  → `alembic stamp head` lo adotta senza ricrearlo (transizione trasparente).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger("api.db")

_APP_ROOT = Path(__file__).resolve().parent.parent  # /app


class Base(DeclarativeBase):
    pass


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(_async_url(settings.database_url), future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def _alembic_config() -> Config:
    cfg = Config(str(_APP_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_APP_ROOT / "alembic"))
    return cfg


async def _db_state() -> tuple[bool, bool]:
    async with engine.connect() as conn:
        has_alembic = await conn.run_sync(lambda c: sa.inspect(c).has_table("alembic_version"))
        has_alerts = await conn.run_sync(lambda c: sa.inspect(c).has_table("alerts"))
    return has_alembic, has_alerts


async def run_migrations() -> None:
    from app import models  # noqa: F401  (registra i modelli sul metadata)

    delay = 2
    for _ in range(6):
        try:
            has_alembic, has_alerts = await _db_state()
            break
        except Exception as exc:  # noqa: BLE001 — attesa disponibilità DB in dev
            logger.warning("DB non pronto (%s): retry tra %ss", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
    else:
        logger.error("DB non raggiungibile: migrazioni saltate")
        return

    cfg = _alembic_config()
    if has_alerts and not has_alembic:
        # DB creato in passato con create_all (schema = baseline 0001): lo
        # "adotto" marcando 0001 come applicata, POI applico le migrazioni
        # successive (0002, ...). Stampare "head" salterebbe le ALTER.
        logger.info("DB preesistente (create_all): stamp baseline 0001 + upgrade head")
        await asyncio.to_thread(command.stamp, cfg, "0001")
    await asyncio.to_thread(command.upgrade, cfg, "head")


async def init_db() -> None:
    await run_migrations()
    # Il seeding è NON fatale: un suo errore non deve rendere irraggiungibile
    # l'intera API (le migrazioni, invece, restano fatali: schema corretto).
    for seed in (_seed_sources, _seed_subjects):
        try:
            await seed()
        except Exception:  # noqa: BLE001
            logger.exception("Seed %s fallito (non fatale): l'API parte comunque", seed.__name__)


async def _seed_sources() -> None:
    from sqlalchemy import select

    from app.models import Source

    seed = [
        Source(id="dowjones", nome="Dow Jones Risk & Compliance", tipo="feed",
               credibilita="alta", rischio_legale="basso"),
        Source(id="anac-bdncp", nome="BDNCP — ANAC (via PDND)", tipo="api",
               credibilita="alta", rischio_legale="basso"),
        Source(id="albo-pretorio", nome="Albo pretorio (comune X)", tipo="scraping",
               credibilita="alta", rischio_legale="basso", crawl_delay_s=3.0),
        # Feed di rischio strutturato (B9): capability progettata (risk-gateway),
        # non ancora attiva. rischio_legale "medio" perché invia identità reale a
        # un processore esterno (DPA/DPIA richiesti). attiva=False = sospesa.
        Source(id="crimetech", nome="Crime&tech — Risk Indicators (AML/CFT)", tipo="feed",
               credibilita="alta", rischio_legale="medio", attiva=False),
        # Fonti istituzionali candidate (B10), catalogate ma non ancora integrate.
        # White List antimafia: check per identità AUTORITATIVO e segnale POSITIVO
        # (impresa verificata). Accesso accreditato BDNA / portale nazionale; nessuna
        # API aperta. Rischio legale basso (registro pubblico).
        Source(id="white-list", nome="White List Antimafia (Prefetture / BDNA)", tipo="registro",
               credibilita="alta", rischio_legale="basso", attiva=False),
        # Banca Dati di Merito (sentenze civili, Min. Giustizia): pubblica ma
        # PSEUDONIMIZZATA e con DIVIETO ESPRESSO di profilazione/comparazione →
        # NON utilizzabile per screening per identità. Catalogata come ESCLUSA;
        # rischio_legale "alto" per marcare il vincolo.
        Source(id="banca-dati-merito", nome="Banca Dati di Merito — sentenze civili (Min. Giustizia)",
               tipo="banca dati", credibilita="alta", rischio_legale="alto", attiva=False),
    ]
    async with SessionLocal() as session:
        existing = (await session.execute(select(Source.id))).scalars().all()
        for s in seed:
            if s.id not in existing:
                session.add(s)
        await session.commit()


async def _seed_subjects() -> None:
    """Seed dimostrativo del registro soggetti (anti-omonimia). In produzione
    sincronizzato da ReGiS/OpenCoesione/InfoCamere; qui popola il registro al
    primo avvio così ER trova i soggetti demo (e la console può aggiungerne)."""
    from sqlalchemy import select

    from app.models import Subject

    seed = [
        Subject(id="R-ACME", tipo_soggetto="persona_giuridica", denominazione="ACME Costruzioni S.r.l.",
                cf_piva="00743110157", cup=["E51B21000000001"], ruolo="impresa esecutrice"),
        Subject(id="R-ACME-GEN", tipo_soggetto="persona_giuridica", denominazione="ACME Costruzioni Generali S.r.l.",
                cf_piva="09876543217", cup=["E51B21000000009"], ruolo="impresa esecutrice"),
        Subject(id="R-BETA", tipo_soggetto="persona_giuridica", denominazione="Beta Infrastrutture S.p.A.",
                cf_piva="12345670159", cup=["B22C21000000002"], ruolo="beneficiario"),
        Subject(id="R-TRON", tipo_soggetto="persona_giuridica", denominazione="Tron Group Holding S.r.l.",
                cf_piva="12345678903", cup=["G29J24000000003"], ruolo="impresa esecutrice"),
        Subject(id="R-ROSSI-1", tipo_soggetto="persona_fisica", denominazione="Rossi Mario",
                cf_piva="RSSMRA75C15H501P", data_nascita="1975-03-15", luogo_nascita="Roma",
                cup=["E51B21000000001"], ruolo="RUP"),
        Subject(id="R-ROSSI-2", tipo_soggetto="persona_fisica", denominazione="Rossi Mario",
                cf_piva="RSSMRA80E20F205I", data_nascita="1980-05-20", luogo_nascita="Milano",
                cup=["G29J24000000003"], ruolo="legale rappresentante"),
        Subject(id="R-BIANCHI", tipo_soggetto="persona_fisica", denominazione="Bianchi Giulia",
                cf_piva="BNCGLI82S43H501W", data_nascita="1982-11-03", luogo_nascita="Roma",
                cup=["B22C21000000002"], ruolo="amministratore"),
    ]
    async with SessionLocal() as session:
        existing = (await session.execute(select(Subject.id))).scalars().all()
        if existing:
            return  # registro già popolato (non re-seedare)
        for s in seed:
            session.add(s)
        await session.commit()
