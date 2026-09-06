"""Configurazione del search-gateway (ricerca articoli adverse media)."""
from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # Provider di ricerca: "mock" (default locale, nessuna rete) | "gdelt" (news
    # globale keyless, ma rate-limited/instabile) | "brave" (Brave Search API,
    # a chiave, affidabile). Altri (SerpAPI/CSE, feed licenziati) si innestano
    # sull'astrazione in providers.py.
    search_provider: str = "mock"

    # Numero massimo di risultati per ricerca.
    search_max_results: int = 10

    # Filtro lingua GDELT (nome lingua GDELT, es. "italian"). Vuoto = nessun filtro.
    search_default_lang: str = "italian"

    # Finestra temporale GDELT (es. 24h, 1w, 3m, 6m, 1y).
    search_timespan: str = "12m"

    # Endpoint GDELT DOC 2.0 API (keyless).
    gdelt_endpoint: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    # UA "browser" per le chiamate GDELT: alcuni CDN penalizzano gli UA bot.
    gdelt_user_agent: str = "Mozilla/5.0 (compatible; AdverseMediaScreening/0.1)"

    # Brave Search API (provider "brave"): chiave e endpoint news. Free tier
    # generoso; nessuna chiave nel repo (solo via .env).
    brave_api_key: str = ""
    brave_endpoint: str = "https://api.search.brave.com/res/v1/news/search"
    brave_country: str = "it"
    # GDELT è rate-limited (~1 req/5s per IP). Intervallo minimo tra chiamate
    # (throttle in-process), retry dopo un 429 (n. tentativi + attesa base/cap).
    gdelt_min_interval: float = 5.0
    gdelt_retries: int = 2
    gdelt_retry_wait: float = 5.0
    gdelt_max_wait: float = 12.0

    # Cache in-memory delle risposte di ricerca (TTL secondi): evita di ribattere
    # su GDELT per ricerche ripetute nel loop di test. 0 = disattivata.
    search_cache_ttl: int = 900

    # Deduplica per dominio: un (max_per_domain) articolo per testata.
    dedup_by_domain: bool = True
    max_per_domain: int = 1
    # Over-fetch: quanti risultati grezzi chiedere al provider rispetto al
    # richiesto, per avere abbastanza domini distinti dopo la dedup.
    dedup_overfetch: int = 4

    # Filtro credibilità: soglia minima ("none" = nessun filtro, solo annotazione).
    # Valori: none | bassa | media | alta.
    min_credibility: str = "none"

    # User-Agent identificabile (riusa quello dello scraper).
    user_agent: str = Field(
        default="AdverseMediaBot/0.1 (+contatto: esempio@amministrazione.it)",
        validation_alias=AliasChoices("SEARCH_USER_AGENT", "SCRAPER_USER_AGENT"),
    )
    request_timeout: float = 20.0


settings = Settings()
