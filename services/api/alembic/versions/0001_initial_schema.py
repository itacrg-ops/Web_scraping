"""schema iniziale: sources, screenings, alerts, evidence

Revision ID: 0001
Revises:
Create Date: 2026-09-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("nome", sa.String(), nullable=False),
        sa.Column("tipo", sa.String(), nullable=False),
        sa.Column("credibilita", sa.String(), nullable=False),
        sa.Column("rischio_legale", sa.String(), nullable=False),
        sa.Column("crawl_delay_s", sa.Float(), nullable=False),
        sa.Column("respect_robots", sa.Boolean(), nullable=False),
        sa.Column("attiva", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "screenings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("denominazione", sa.String(), nullable=False),
        sa.Column("cf_piva", sa.String(), nullable=True),
        sa.Column("cup", sa.JSON(), nullable=False),
        sa.Column("seed_url", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("alert_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("screening_id", sa.String(), sa.ForeignKey("screenings.id"), nullable=True),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("cf_piva", sa.String(), nullable=True),
        sa.Column("cup", sa.JSON(), nullable=False),
        sa.Column("ami_score", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(), nullable=False),
        sa.Column("fatf_categories", sa.JSON(), nullable=False),
        sa.Column("drivers", sa.JSON(), nullable=False),
        sa.Column("disposition", sa.String(), nullable=False),
        sa.Column("svi_alert_id", sa.String(), nullable=True),
        sa.Column("entity_resolution", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("alert_id", sa.String(), sa.ForeignKey("alerts.id"), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("testata", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("data", sa.String(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("fetch_ts", sa.String(), nullable=True),
        sa.Column("bucket", sa.String(), nullable=True),
        sa.Column("raw_key", sa.String(), nullable=True),
        sa.Column("warc_key", sa.String(), nullable=True),
        sa.Column("fonte_credibilita", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("evidence")
    op.drop_table("alerts")
    op.drop_table("screenings")
    op.drop_table("sources")
