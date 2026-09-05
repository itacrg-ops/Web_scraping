"""aggiunge tipo_soggetto a screenings e alerts (persona fisica | giuridica)

Consente lo screening di **persone fisiche** (ricerca per nome e cognome) oltre
che di entità. Le righe preesistenti sono retro-compatibili: default
"persona_giuridica" via server_default (backfill) e default lato ORM sui nuovi
insert.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT = "persona_giuridica"


def upgrade() -> None:
    for table in ("screenings", "alerts"):
        op.add_column(
            table,
            sa.Column("tipo_soggetto", sa.String(), nullable=False, server_default=_DEFAULT),
        )


def downgrade() -> None:
    for table in ("alerts", "screenings"):
        op.drop_column(table, "tipo_soggetto")
