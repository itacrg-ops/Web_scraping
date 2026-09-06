"""Configurazione del servizio Entity Resolution."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # Il registro dei soggetti è il sistema di record dell'API (Postgres): ER lo
    # legge da qui con una cache TTL. Se l'API non è raggiungibile, ER usa un
    # piccolo seed di fallback (resilienza all'avvio).
    api_url: str = "http://api:8000"
    registry_ttl: float = 30.0

    # Soglie di matching sul nome (quando manca un identificatore forte).
    name_high: float = 0.92      # sopra: match sul nome "forte"
    name_candidate: float = 0.78  # sopra: candidato da considerare
    name_margin: float = 0.05     # distacco minimo dal secondo candidato

    # Anti-omonimia: per default il solo nome NON supera il gate (serve un
    # identificatore CF/P.IVA in registro). Attivabile con cautela per contesti
    # in cui il nome è sufficiente (es. denominazioni univoche verificate).
    allow_name_only_resolution: bool = False

    # Screening ESPLORATIVO (default OFF): se il soggetto NON è a registro
    # (nessun candidato), consente di procedere con una risoluzione PROVVISORIA
    # e non autoritativa. Utile in locale per esercitare la pipeline su qualsiasi
    # nome; in produzione è un'azione deliberata dell'analista (alert marcato).
    allow_unregistered_subject: bool = False


settings = Settings()
