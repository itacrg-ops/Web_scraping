"""alert: esito SVI separato (svi_status/svi_error), un solo alert per screening;
screening: motivo del fallimento (error)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-23

Il worker ora salva l'alert PRIMA di pubblicarlo in SVI e registra l'esito della
pubblicazione a parte. La persistenza è idempotente per screening (unique su
`alerts.screening_id`).

Nei DB esistenti i retry del vecchio flusso possono aver creato più alert per lo
stesso screening: prima di creare il vincolo, i duplicati vengono SGANCIATI
(screening_id = NULL) — non cancellati — tenendo agganciato quello referenziato da
`screenings.alert_id` (o, in mancanza, il più vecchio).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("svi_status", sa.String(), nullable=False,
                                      server_default="pending"))
    op.add_column("alerts", sa.Column("svi_error", sa.Text(), nullable=True))
    op.add_column("screenings", sa.Column("error", sa.Text(), nullable=True))

    # Alert preesistenti: col vecchio flusso l'alert si salvava DOPO la pubblicazione,
    # quindi con svi_alert_id → pubblicato; senza (ER non superata) → non pubblicato.
    op.execute("UPDATE alerts SET svi_status = CASE WHEN svi_alert_id IS NOT NULL "
               "THEN 'published' ELSE 'skipped' END")

    # Duplicati per screening: tieni agganciato quello referenziato dallo screening
    # (o il più vecchio), sgancia gli altri. Nessuna riga viene cancellata.
    op.execute("""
        WITH ranked AS (
            SELECT a.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY a.screening_id
                       ORDER BY (a.id = s.alert_id) DESC NULLS LAST, a.created_at ASC, a.id ASC
                   ) AS rn
            FROM alerts a
            LEFT JOIN screenings s ON s.id = a.screening_id
            WHERE a.screening_id IS NOT NULL
        )
        UPDATE alerts SET screening_id = NULL
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
    """)
    op.create_unique_constraint("uq_alerts_screening_id", "alerts", ["screening_id"])


def downgrade() -> None:
    op.drop_constraint("uq_alerts_screening_id", "alerts", type_="unique")
    op.drop_column("screenings", "error")
    op.drop_column("alerts", "svi_error")
    op.drop_column("alerts", "svi_status")
