"""Configurazione del servizio Entity Resolution."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # Soglie di matching sul nome (quando manca un identificatore forte).
    name_high: float = 0.92      # sopra: match sul nome "forte"
    name_candidate: float = 0.78  # sopra: candidato da considerare
    name_margin: float = 0.05     # distacco minimo dal secondo candidato

    # Anti-omonimia: per default il solo nome NON supera il gate (serve un
    # identificatore CF/P.IVA in registro). Attivabile con cautela per contesti
    # in cui il nome è sufficiente (es. denominazioni univoche verificate).
    allow_name_only_resolution: bool = False


settings = Settings()
