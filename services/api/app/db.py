"""Persistenza: engine SQLAlchemy async + inizializzazione con retry + seed.

Postgres è il **sistema di record**. In dev le tabelle sono create con
`create_all`; in produzione si passerà ad **Alembic** (migrazioni versionate).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger("api.db")


class Base(DeclarativeBase):
    pass


def _async_url(url: str) -> str:
    # asyncpg richiede il driver esplicito nell'URL.
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(_async_url(settings.database_url), future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Crea le tabelle (con retry: Postgres può non essere ancora pronto) e semina le fonti."""
    from app import models  # noqa: F401  (registra i modelli sul metadata)

    delay = 2
    for attempt in range(6):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Dev shim (finché non c'è Alembic): aggiunge colonne nuove a
                # tabelle già esistenti, così non serve ricreare il volume DB.
                await conn.execute(
                    text("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS entity_resolution JSONB")
                )
            break
        except Exception as exc:  # noqa: BLE001 — attesa disponibilità DB in dev
            logger.warning("DB non pronto (%s): retry tra %ss", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
    else:
        logger.error("Impossibile inizializzare il DB dopo i tentativi previsti")
        return

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
