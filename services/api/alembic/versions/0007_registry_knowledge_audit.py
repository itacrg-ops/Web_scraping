"""registro arricchito dai revisori (nomi simili, articoli confermati), audit delle
operazioni sensibili, varianti del nome trovate negli articoli

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-23

- subject_names: decisioni su nomi simili a un soggetto del registro («stesso»: variante
  o refuso dello stesso soggetto → alias per l'Entity Resolution; «diverso»: altro
  soggetto da non confondere);
- subject_articles: articoli confermati per un soggetto a valle dell'etichettatura
  (lo riguardano o no, sono avversi o no, con il giudizio sul caso);
- audit_log: chi ha cancellato alert, corretto nomi del registro, confermato articoli;
- alerts.name_variants: varianti vicine al nome del soggetto citate negli articoli che
  NON citano il nome esatto (es. «Andrea Stroppa» per «Stropp Andrea»: refuso?).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("name_variants", sa.JSON(), nullable=True))
    op.create_table(
        "subject_names",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("subject_id", sa.String(), sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_key", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_by_name", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("subject_id", "name_key", name="uq_subject_names_subject_key"),
    )
    op.create_index("ix_subject_names_subject_id", "subject_names", ["subject_id"])
    op.create_table(
        "subject_articles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("subject_id", sa.String(), sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_id", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("testata", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("data", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("pertinenza", sa.String(), nullable=False),
        sa.Column("avversa", sa.String(), nullable=False),
        sa.Column("categorie", sa.JSON(), nullable=False),
        sa.Column("ruolo", sa.String(), nullable=True),
        sa.Column("esito", sa.String(), nullable=True),
        sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("confirmed_by_name", sa.String(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("subject_id", "url", name="uq_subject_articles_subject_url"),
    )
    op.create_index("ix_subject_articles_subject_id", "subject_articles", ["subject_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(), nullable=True),
        sa.Column("actor_name", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("object_id", sa.String(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
    )
    op.create_index("ix_audit_log_object", "audit_log", ["object_type", "object_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_object", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_subject_articles_subject_id", table_name="subject_articles")
    op.drop_table("subject_articles")
    op.drop_index("ix_subject_names_subject_id", table_name="subject_names")
    op.drop_table("subject_names")
    op.drop_column("alerts", "name_variants")
