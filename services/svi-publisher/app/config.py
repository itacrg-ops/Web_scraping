"""Configurazione del publisher verso SAS Visual Investigator (SVI)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # "mock" (default in locale, nessuna Viya) | "live" (ambiente Viya/SVI reale)
    svi_mode: str = "mock"

    # --- Endpoint SVI (usati solo in "live") ---
    viya_endpoint: str = ""              # es. https://viya.example.org
    svi_datahub_base: str = ""           # default: {viya}/svi-datahub
    svi_alerts_base: str = ""            # default: {viya}/svi-alert

    # --- Autenticazione (solo "live") ---
    #   "oauth"  -> OAuth2 SASLogon ({viya}/SASLogon/oauth/token)
    #   "broker" -> token di servizio da un sidecar (sas_token_broker_url)
    svi_auth_mode: str = "oauth"
    sas_token_broker_url: str = "http://sas-token-broker:8099/token"
    # OAuth2: grant "client_credentials" (default) o "password".
    sas_oauth_grant: str = "client_credentials"
    sas_client_id: str = ""              # MAI nel repo: solo via .env
    sas_client_secret: str = ""          # MAI nel repo: solo via .env
    sas_username: str = ""               # solo grant "password"
    sas_password: str = ""               # solo grant "password"
    sas_oauth_scope: str = ""            # opzionale (spazio-separato)

    # --- Modello dati SVI (deployment-specific: valorizzare da .env) ---
    # I nomi di tipo oggetto/alert/coda dipendono dal data model configurato nel
    # cliente: qui default sensati, sovrascrivibili senza toccare il codice.
    svi_object_type: str = "adverse_media_alert"    # tipo documento nel Data Hub
    svi_alert_type: str = "AdverseMediaAlert"        # tipo alert
    svi_queue: str = "screening-primo-livello"       # coda di destinazione (I livello)
    svi_source_system: str = "adverse-media-screening"
    svi_external_id_attr: str = "externalId"         # attributo per la dedup lato SVI

    # --- Robustezza ---
    svi_request_timeout: float = 30.0
    svi_max_retries: int = 3
    svi_retry_backoff: float = 1.5       # base backoff (s): 1.5, 3.0, 6.0...
    svi_idempotency_ttl: int = 86400     # cache business_key -> id (s)

    def datahub_base(self) -> str:
        return self.svi_datahub_base or (self.viya_endpoint.rstrip("/") + "/svi-datahub")

    def alerts_base(self) -> str:
        return self.svi_alerts_base or (self.viya_endpoint.rstrip("/") + "/svi-alert")

    def token_url(self) -> str:
        return self.viya_endpoint.rstrip("/") + "/SASLogon/oauth/token"


settings = Settings()
