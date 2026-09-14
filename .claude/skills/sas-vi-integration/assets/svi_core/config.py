"""Configurazione generica dell'integrazione SAS Visual Investigator.

Riusa `pydantic-settings`: i valori arrivano da variabili d'ambiente / `.env` (prefisso
`SVI_`/`SAS_`/`VIYA_`). **Segreti solo in `.env`, mai nel codice.** Vedi
`templates/.env.svi.example` per il set completo con commenti.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SviConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "mock" (nessuna Viya, id fittizi) | "live" (ambiente Viya/SVI reale)
    svi_mode: str = "mock"

    # --- Endpoint (solo live) ---
    viya_endpoint: str = ""              # es. https://viya.example.org
    svi_datahub_base: str = ""           # default: {viya}/svi-datahub
    svi_alerts_base: str = ""            # default: {viya}/svi-alert

    # --- Autenticazione (solo live) ---
    #   "oauth"  -> SASLogon {viya}/SASLogon/oauth/token (grant client_credentials|password)
    #   "token"  -> bearer già ottenuto in SAS_BEARER_TOKEN (scade: test/pilota)
    #   "broker" -> token di servizio da un sidecar (SAS_TOKEN_BROKER_URL)
    svi_auth_mode: str = "oauth"
    sas_bearer_token: str = ""
    sas_token_broker_url: str = "http://sas-token-broker:8099/token"
    sas_oauth_grant: str = "client_credentials"
    sas_client_id: str = ""
    sas_client_secret: str = ""
    sas_username: str = ""
    sas_password: str = ""
    sas_oauth_scope: str = ""

    # --- Modello alert (deployment-specific: ricavati con svi_inspect.py) ---
    svi_entity_type: str = ""            # actionableEntityType (entity type in SVI)
    svi_queue: str = ""                  # recommendedQueueId (coda con acceptManualAlerts=true)
    svi_alert_type_code: str = "strategy_default"   # alertTypeCode (OBBLIGATORIO lato SVI)
    svi_alert_origin: str = ""           # alertOriginCode (vuoto = omesso)

    # Creazione alert: POST /svi-alert/alertingEvents (envelope jsonLayout flat).
    # Media type versionato SAS (il suffisso +json;version=1 è obbligatorio).
    svi_alertingevent_media_type: str = (
        "application/vnd.sas.investigation.triage.alerting.data.flat+json;version=1"
    )

    # Sezioni opzionali dell'envelope (off di default: SVI può validarne le chiavi).
    svi_send_enrichment: bool = False
    svi_send_scenario_events: bool = False
    svi_send_contributing_objects: bool = False

    # errorCode 1008 = "data error" AMBIGUO (duplicato OPPURE riferimento non valido:
    # dominio/coda/entityType/alertTypeCode inesistenti). Default: sollevalo (alert NON
    # creato). True SOLO in ambienti a riferimenti validi dove vuoi ripubblicazioni
    # idempotenti (1008 = duplicato).
    svi_dedup_on_1008: bool = False

    # --- Robustezza ---
    svi_request_timeout: float = 30.0
    svi_max_retries: int = 3
    svi_retry_backoff: float = 1.5       # base (s): 1.5, 3.0, 6.0...
    svi_idempotency_ttl: int = 86400     # cache business_key -> id (s)

    # --- TLS ---
    svi_verify_tls: bool = True          # False SOLO per demo self-signed (== curl -k)
    svi_ca_bundle: str = ""              # meglio: path al certificato/CA (verifica attiva)

    def verify_opt(self):
        """Valore `verify` per httpx: CA bundle se impostato, altrimenti il bool."""
        return self.svi_ca_bundle or self.svi_verify_tls

    def datahub_base(self) -> str:
        return self.svi_datahub_base or (self.viya_endpoint.rstrip("/") + "/svi-datahub")

    def alerts_base(self) -> str:
        return self.svi_alerts_base or (self.viya_endpoint.rstrip("/") + "/svi-alert")

    def token_url(self) -> str:
        return self.viya_endpoint.rstrip("/") + "/SASLogon/oauth/token"


# Istanza comoda (letta da .env/ambiente). Le app possono anche istanziare SviConfig().
settings = SviConfig()
