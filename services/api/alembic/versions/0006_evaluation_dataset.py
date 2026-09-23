"""dataset di valutazione: predizioni del sistema (evidenze, classificazione) ed
etichette dei revisori (case_labels)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-23

Per misurare quanti errori fa il sistema servono, sugli stessi casi, la predizione
del sistema e il giudizio umano:
- evidence.mentioned / mention_match: il sistema ritiene il soggetto citato
  nell'articolo (e come);
- alerts.classification: metodo (LLM o parole chiave), severità, ruolo…;
- case_labels: l'etichetta del revisore, una per alert e revisore.
Le righe preesistenti restano con predizioni NULL (non ricostruibili a posteriori).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("mentioned", sa.Boolean(), nullable=True))
    op.add_column("evidence", sa.Column("mention_match", sa.JSON(), nullable=True))
    op.add_column("alerts", sa.Column("classification", sa.JSON(), nullable=True))
    op.create_table(
        "case_labels",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("alert_id", sa.String(), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=False),
        sa.Column("reviewer_name", sa.String(), nullable=True),
        sa.Column("evidence_labels", sa.JSON(), nullable=False),
        sa.Column("categorie_corrette", sa.JSON(), nullable=False),
        sa.Column("ruolo", sa.String(), nullable=True),
        sa.Column("disposition_attesa", sa.String(), nullable=True),
        sa.Column("affidabile", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("alert_id", "reviewer", name="uq_case_labels_alert_reviewer"),
    )
    op.create_index("ix_case_labels_alert_id", "case_labels", ["alert_id"])


def downgrade() -> None:
    op.drop_index("ix_case_labels_alert_id", table_name="case_labels")
    op.drop_table("case_labels")
    op.drop_column("alerts", "classification")
    op.drop_column("evidence", "mention_match")
    op.drop_column("evidence", "mentioned")
