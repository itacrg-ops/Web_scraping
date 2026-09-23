"""Registro dei soggetti noti: letto dall'API (sistema di record su Postgres)
con cache TTL, autenticandosi col token di servizio (endpoint interno).

Se l'API non risponde si usa la cache stantia. Il seed dimostrativo di fallback
vale SOLO in `APP_ENV=development` (ordine di avvio dei container in locale): in
ogni altro ambiente, senza registro, nessun soggetto viene risolto (il gate si
astiene) invece di confrontare i soggetti reali con dati demo.
"""
from __future__ import annotations

import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger("entity-resolution.registry")

PERSONA_FISICA = "persona_fisica"
PERSONA_GIURIDICA = "persona_giuridica"

# Seed di fallback (stesso contenuto del seed DB lato API) — solo per resilienza.
_FALLBACK: list[dict] = [
    {"id": "R-ACME", "tipo": PERSONA_GIURIDICA, "denominazione": "ACME Costruzioni S.r.l.",
     "cf_piva": "00743110157", "cup": ["E51B21000000001"], "ruolo": "impresa esecutrice"},
    {"id": "R-ACME-GEN", "tipo": PERSONA_GIURIDICA, "denominazione": "ACME Costruzioni Generali S.r.l.",
     "cf_piva": "09876543217", "cup": ["E51B21000000009"], "ruolo": "impresa esecutrice"},
    {"id": "R-BETA", "tipo": PERSONA_GIURIDICA, "denominazione": "Beta Infrastrutture S.p.A.",
     "cf_piva": "12345670159", "cup": ["B22C21000000002"], "ruolo": "beneficiario"},
    {"id": "R-TRON", "tipo": PERSONA_GIURIDICA, "denominazione": "Tron Group Holding S.r.l.",
     "cf_piva": "12345678903", "cup": ["G29J24000000003"], "ruolo": "impresa esecutrice"},
    {"id": "R-ROSSI-1", "tipo": PERSONA_FISICA, "denominazione": "Rossi Mario",
     "cf_piva": "RSSMRA75C15H501P", "data_nascita": "1975-03-15", "luogo_nascita": "Roma",
     "cup": ["E51B21000000001"], "ruolo": "RUP"},
    {"id": "R-ROSSI-2", "tipo": PERSONA_FISICA, "denominazione": "Rossi Mario",
     "cf_piva": "RSSMRA80E20F205I", "data_nascita": "1980-05-20", "luogo_nascita": "Milano",
     "cup": ["G29J24000000003"], "ruolo": "legale rappresentante"},
    {"id": "R-BIANCHI", "tipo": PERSONA_FISICA, "denominazione": "Bianchi Giulia",
     "cf_piva": "BNCGLI82S43H501W", "data_nascita": "1982-11-03", "luogo_nascita": "Roma",
     "cup": ["B22C21000000002"], "ruolo": "amministratore"},
]

_cache: dict = {"ts": 0.0, "data": None}


def get_registry() -> list[dict]:
    """Registro corrente (cache TTL). Non solleva: su errore usa la cache stantia;
    senza cache, il seed di fallback in sviluppo, altrimenti un registro vuoto."""
    now = time.monotonic()
    if _cache["data"] is not None and (now - _cache["ts"]) < settings.registry_ttl:
        return _cache["data"]
    headers = {"X-Internal-Token": settings.internal_api_token} if settings.internal_api_token else None
    try:
        r = httpx.get(f"{settings.api_url}/api/subjects/registry", headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json().get("subjects", [])
            _cache["data"] = data
            _cache["ts"] = now
            logger.info("registro aggiornato dall'API: %d soggetti", len(data))
            return data
        if r.status_code in (401, 503):
            logger.error("registry API %s: token interno mancante o diverso da quello dell'API "
                         "(INTERNAL_API_TOKEN deve essere uguale su api ed entity-resolution)",
                         r.status_code)
        else:
            logger.warning("registry API status %s", r.status_code)
    except Exception as exc:  # noqa: BLE001 — non fatale
        logger.warning("registry API non raggiungibile (%s)", exc)
    if _cache["data"] is not None:
        return _cache["data"]
    if settings.app_env == "development":
        return _FALLBACK
    logger.error("registro soggetti non disponibile e nessuna cache: nessun soggetto risolvibile")
    return []
