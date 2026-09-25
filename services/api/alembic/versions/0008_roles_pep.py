"""ruoli della persona negli articoli e flag PEP (alert e registro)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-25

- alerts.roles: ruoli scritti accanto al nome negli articoli (cariche PEP, politiche,
  aziendali), con in quanti articoli compaiono; alerts.pep: possibile persona
  politicamente esposta (D.Lgs. 231/2007), NULL per le persone giuridiche;
- subjects.pep e subjects.cariche: flag PEP e ruoli confermati dai revisori nel registro
  (distinti da subjects.ruolo, il ruolo nell'intervento: beneficiario, RUP…).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("roles", sa.JSON(), nullable=True))
    op.add_column("alerts", sa.Column("pep", sa.Boolean(), nullable=True))
    op.add_column("subjects", sa.Column("pep", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("subjects", sa.Column("cariche", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("subjects", "cariche")
    op.drop_column("subjects", "pep")
    op.drop_column("alerts", "pep")
    op.drop_column("alerts", "roles")
