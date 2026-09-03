"""Configurazione del gateway LLM verso Azure AI Foundry."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # Endpoint del progetto Azure AI Foundry / Azure OpenAI (region UE).
    azure_foundry_endpoint: str = ""
    azure_openai_api_version: str = "2024-10-21"

    # Deployment dual-LLM (nomi dei deployment su Foundry).
    llm_model_primary: str = ""
    llm_model_secondary: str = ""
    embedding_model: str = ""

    # Backpressure allineato alle quote Foundry.
    llm_max_rpm: int = 60
    llm_max_tpm: int = 60000

    # Redazione PII prima dell'invio all'LLM (default: attiva).
    pii_redaction: bool = True

    # Auth: DefaultAzureCredential.
    #  - locale : service principal di sviluppo via AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET
    #  - prod   : AKS Workload Identity (nessuna chiave statica)
    # La scope OAuth per Azure OpenAI/Cognitive Services:
    azure_cognitive_scope: str = "https://cognitiveservices.azure.com/.default"


settings = Settings()
