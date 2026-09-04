"""Configurazione dell'API back-end (12-factor: tutto da variabili d'ambiente)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    # Store (default coerente col docker-compose.dev.yml)
    database_url: str = "postgresql://ams:ams@postgres:5432/ams"
    redis_url: str | None = None

    # Task queue Temporal su cui gira il worker di scraping
    scraping_task_queue: str = "scraping"

    # Servizi interni
    llm_gateway_url: str = "http://llm-gateway:8080"
    svi_publisher_url: str = "http://svi-publisher:8090"
    temporal_host: str = "temporal:7233"

    # CORS: origini ammesse per la console di amministrazione React
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


settings = Settings()
