"""Dispatch dei provider del feed di rischio.

Astrazione unica `assess(subject)` che sceglie il provider da `RISK_PROVIDER`:
    ""         -> DISATTIVO (default): assessment non disponibile, nessun egress
    "mock"     -> profilo da fixture locale (collaudo offline della mappatura)
    "crimetech"-> client Crime&tech (stub: guardie hard, spec pending)

Il worker chiama sempre questa funzione: la logica di attivazione vive qui, non
nella pipeline. Contratto di ritorno **stabile** (vedi `mapping.build_assessment`
e `mapping.unavailable`), così il worker arricchisce l'alert solo se disponibile.
"""
from __future__ import annotations

from typing import Any

from app import crimetech, fixtures, mapping
from app.config import settings


def active_provider() -> str:
    return (settings.risk_provider or "").strip().lower()


def assess(subject: dict[str, Any]) -> dict[str, Any]:
    provider = active_provider()
    if not provider:
        return mapping.unavailable("nessuno", "feed di rischio disattivato (RISK_PROVIDER vuoto)")

    if provider == "mock":
        raw = fixtures.demo_profile()
        return mapping.build_assessment("mock", raw)

    if provider == "crimetech":
        raw, reason = crimetech.fetch(subject)
        if raw is None:
            return mapping.unavailable("crimetech", reason)
        return mapping.build_assessment("crimetech", raw)

    return mapping.unavailable(provider, f"provider di rischio sconosciuto: {provider}")


def status() -> dict[str, Any]:
    """Stato del feed per l'introspezione/console."""
    provider = active_provider()
    live_ok, why = crimetech._live_enabled()
    return {
        "active": provider or None,
        "enabled": bool(provider),
        "providers": [
            {"id": "mock", "nome": "Mock (fixture locale)", "tipo": "feed rischio, offline",
             "configurato": True, "attivo": provider == "mock",
             "note": "Profilo dimostrativo: collaudo della mappatura senza rete."},
            {"id": "crimetech", "nome": "Crime&tech — Risk Indicators (AML/CFT)",
             "tipo": "feed rischio, a chiave", "configurato": bool(settings.crimetech_api_key),
             "attivo": provider == "crimetech",
             "note": ("Live pronto" if live_ok else f"Stub: {why}")
             + ". Invia identità reale a processore esterno: richiede DPA/DPIA."},
        ],
    }
