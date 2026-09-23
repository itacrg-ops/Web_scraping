"""Registro delle operazioni sensibili (audit): cancellazioni di alert, correzioni del
registro, decisioni sui nomi, conferme di articoli. Chi, quando, cosa: i dettagli
contengono identificativi e motivi, non i dati personali del soggetto."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import User
from app.models import AuditLog


def record(session: AsyncSession, user: User, action: str, object_type: str, object_id: str,
           **details) -> None:
    """Aggiunge la voce alla sessione: la salva il commit dell'operazione stessa."""
    session.add(AuditLog(actor=user.sub or user.name, actor_name=user.name, action=action,
                         object_type=object_type, object_id=object_id, details=details or None))
