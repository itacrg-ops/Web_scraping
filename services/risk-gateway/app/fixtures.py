"""Fixture locali per il provider `mock` del feed di rischio.

Servono a collaudare **offline** la mappatura e l'aggancio nel workflow, senza
toccare la rete né dipendere dall'API reale. La forma è quella **normalizzata**
attesa da `mapping.build_assessment` (già tradotta dai campi grezzi del provider).
"""
from __future__ import annotations

from typing import Any

# Profilo demo: soggetto con un indicatore di corruzione "alto" e una
# connessione a rischio verso un'entità in odore di criminalità organizzata.
_DEMO_PROFILE: dict[str, Any] = {
    "entity_id": "MOCK-ENT-0001",
    "risk_indicators": [
        {"indicator": "Coinvolgimento in procedimenti per corruzione",
         "crime_type": "corruption", "rating": "high", "score": 0.82,
         "explanation": "Segnalazioni ricorrenti su appalti pubblici (dato dimostrativo)."},
        {"indicator": "Esposizione a reati fiscali",
         "crime_type": "tax", "rating": "medium", "score": 0.5,
         "explanation": "Anomalie societarie pregresse (dato dimostrativo)."},
    ],
    "connections": [
        {"entity": "Omega Trading S.r.l.", "entity_id": "MOCK-ENT-0777",
         "relationship": "socio di controllo", "risk_flag": True,
         "crime_type": "organized crime", "rating": "high"},
        {"entity": "Studio Contabile Bianchi", "entity_id": "MOCK-ENT-0090",
         "relationship": "consulente", "risk_flag": False,
         "crime_type": None, "rating": None},
    ],
}


def demo_profile(entity_id: str | None = None) -> dict[str, Any]:
    prof = {**_DEMO_PROFILE}
    if entity_id:
        prof["entity_id"] = entity_id
    return prof
