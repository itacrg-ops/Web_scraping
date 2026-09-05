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
        logger.info("DB preesistente: adozione con 'alembic stamp head'")
        await asyncio.to_thread(command.stamp, cfg, "head")
    else:
        await asyncio.to_thread(command.upgrade, cfg, "head")


async def init_db() -> None:
    await run_migrations()
    await _seed_sources()


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
    ]
    async with SessionLocal() as session:
        existing = (await session.execute(select(Source.id))).scalars().all()
        for s in seed:
            if s.id not in existing:
                session.add(s)
        await session.commit()
