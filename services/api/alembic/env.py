"""Ambiente Alembic (async, driver asyncpg).

L'URL e il metadata provengono dall'app (app.config / app.db). Le migrazioni
sono scritte a mano; `target_metadata` serve solo all'autogenerate.
"""
from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app import models  # noqa: F401  (registra i modelli sul metadata)
from app.config import settings
from app.db import Base, _async_url

config = context.config
target_metadata = Base.metadata


def _run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_async_url(settings.database_url), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(url=_async_url(settings.database_url), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(_run_async())
