"""rivalutazioni del dataset avviate dalla console

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-25

- replay_runs: rivalutazione on demand dei casi etichettati (pagina Observability):
  chi l'ha avviata, avanzamento, esito per caso e report prima/dopo.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "replay_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("solo_affidabili", sa.Boolean(), nullable=False),
        sa.Column("started_by", sa.String(), nullable=False),
        sa.Column("started_by_name", sa.String(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("counts", sa.JSON(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_replay_runs_created_at", "replay_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_replay_runs_created_at", table_name="replay_runs")
    op.drop_table("replay_runs")
