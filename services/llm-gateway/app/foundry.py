"""Client verso Azure AI Foundry (Azure OpenAI) con autenticazione keyless.

Usa `DefaultAzureCredential`, così lo *stesso codice* funziona:
  - in locale : service principal di sviluppo (variabili AZURE_*), endpoint pubblico;
  - in prod   : AKS Workload Identity (managed identity), Private Endpoint.

Il client è creato *lazy* al primo utilizzo: il servizio parte comunque
(health OK) anche senza credenziali configurate, e in tal caso `classify`
restituisce un errore chiaro.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from openai import AzureOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> AzureOpenAI:
    if not settings.azure_foundry_endpoint:
        raise RuntimeError(
            "AZURE_FOUNDRY_ENDPOINT non configurato: imposta l'endpoint Foundry "
            "e la credenziale (dev SP in locale, Workload Identity in prod)."
        )
    # Import ritardato per non richiedere azure-identity al solo avvio/health.
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), settings.azure_cognitive_scope
    )
    return AzureOpenAI(
        azure_endpoint=settings.azure_foundry_endpoint,
        api_version=settings.azure_openai_api_version,
        azure_ad_token_provider=token_provider,
    )


def _redact(text: str) -> str:
    """Placeholder di redazione PII prima dell'invio all'LLM (§8.7/§10.1).

    TODO: sostituire con un redattore reale (CF, P.IVA, nomi, indirizzi).
    """
    if not settings.pii_redaction:
        return text
    return text  # no-op nello scaffold


def classify(text: str, *, secondary: bool = False) -> str:
    """Classificazione FATF dual-LLM (scaffold: ritorna il contenuto grezzo).

    `secondary=True` instrada sul modello secondario (validazione incrociata).
    """
    model = settings.llm_model_secondary if secondary else settings.llm_model_primary
    if not model:
        raise RuntimeError("Deployment LLM non configurato (LLM_MODEL_PRIMARY/SECONDARY).")

    prompt = _redact(text)
    resp = _client().chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Sei un classificatore di adverse media secondo tassonomia FATF. "
                    "Restituisci categorie, ruolo processuale e confidence in JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    return resp.choices[0].message.content or ""
