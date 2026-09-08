"""Configurazione del risk-gateway (feed di rischio strutturato).

Il risk-gateway è il **punto unico di egress** verso i provider di dati di
rischio esterni (AML/CFT), analogo a `search-gateway` (motori di ricerca) e
`llm-gateway` (Azure). Concentra qui l'autenticazione, il rate-limiting e la
mappatura provider→dominio, così il worker parla solo HTTP interno.

**Default OFF.** `RISK_PROVIDER` vuoto = feed disattivato: il gateway risponde
`available:false` e non esce mai sulla rete. Nessun segreto vive nel repo: la
chiave Crime&tech si passa **solo** via `.env` (mai committato).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # Provider del feed di rischio:
    #   "" (default)  -> DISATTIVO: nessun feed, nessuna chiamata esterna
    #   "mock"        -> profilo di rischio da fixture locale (per collaudo offline)
    #   "crimetech"   -> Crime&tech (richiede chiave + spec + ok compliance)
    risk_provider: str = ""

    # --- Crime&tech (Transcrime / Università Cattolica) — AML/CFT ---
    # Base API documentata. Gli endpoint esatti e i nomi dei campi vanno
    # confermati sull'OpenAPI ufficiale (spec non ancora acquisita).
    crimetech_base_url: str = "https://api.crimetech.app"
    # Dataset di riferimento (path param {dataset_id}); fornito dal provider.
    crimetech_dataset_id: str = ""
    # Chiave API: MAI nel repo. Solo via .env. Vuota = client in modalità stub.
    crimetech_api_key: str = ""
    # Guardia HARD alla chiamata live: la rete viene toccata SOLO se questo flag
    # è esplicitamente true E la chiave è presente. Default false = zero egress.
    crimetech_live: bool = False

    request_timeout: float = 20.0


settings = Settings()
