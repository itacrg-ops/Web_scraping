"""Configurazione del search-gateway (ricerca articoli adverse media)."""
from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # Provider di ricerca: "mock" (default locale, nessuna rete) | "gdelt" (news
    # globale keyless). Altri provider (API key, feed licenziati) si innestano
    # sull'astrazione in providers.py.
    search_provider: str = "mock"

    # Numero massimo di risultati per ricerca.
    search_max_results: int = 10

    # Filtro lingua GDELT (nome lingua GDELT, es. "italian"). Vuoto = nessun filtro.
    search_default_lang: str = "italian"

    # Finestra temporale GDELT (es. 24h, 1w, 3m, 6m, 1y).
    search_timespan: str = "6m"

    # Endpoint GDELT DOC 2.0 API (keyless).
    gdelt_endpoint: str = "https://api.gdeltproject.org/api/v2/doc/doc"

    # User-Agent identificabile (riusa quello dello scraper).
    user_agent: str = Field(
        default="AdverseMediaBot/0.1 (+contatto: esempio@amministrazione.it)",
        validation_alias=AliasChoices("SEARCH_USER_AGENT", "SCRAPER_USER_AGENT"),
    )
    request_timeout: float = 20.0


settings = Settings()
