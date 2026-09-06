"""registro soggetti noti (anti-omonimia), gestibile dalla console

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subjects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tipo_soggetto", sa.String(), nullable=False, server_default="persona_giuridica"),
        sa.Column("denominazione", sa.String(), nullable=False),
        sa.Column("cf_piva", sa.String(), nullable=True),
        sa.Column("data_nascita", sa.String(), nullable=True),
        sa.Column("cup", sa.JSON(), nullable=False),
        sa.Column("ruolo", sa.String(), nullable=True),
        sa.Column("attivo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_subjects_cf_piva", "subjects", ["cf_piva"])


def downgrade() -> None:
    op.drop_index("ix_subjects_cf_piva", table_name="subjects")
    op.drop_table("subjects")
