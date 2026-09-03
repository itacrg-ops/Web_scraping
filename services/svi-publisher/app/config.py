"""Configurazione del publisher verso SAS Visual Investigator."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # "mock" (default in locale) | "live" (verso un ambiente Viya/SVI reale)
    svi_mode: str = "mock"

    # Endpoint SVI (usati solo in modalità "live").
    viya_endpoint: str = ""
    svi_datahub_base: str = ""   # es. {viya}/svi-datahub
    svi_alerts_base: str = ""    # es. {viya}/svi-alert

    # Il token SASLogon di servizio è fornito dal sas-token-broker (sidecar).
    sas_token_broker_url: str = "http://sas-token-broker:8099/token"


settings = Settings()
