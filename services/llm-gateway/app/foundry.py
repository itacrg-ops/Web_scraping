"""Client verso Azure AI Foundry (Azure OpenAI) con autenticazione keyless.

Usa `DefaultAzureCredential`, così lo *stesso codice* funziona:
  - in locale : service principal di sviluppo (variabili AZURE_*), endpoint pubblico;
  - in prod   : AKS Workload Identity (managed identity), Private Endpoint.

Classificazione FATF **dual-LLM** con output **JSON strutturato** e riconciliazione.
Il client è creato *lazy*: il servizio parte comunque (health OK) anche senza
credenziali; in tal caso `classify` solleva un errore chiaro (→ 503).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from openai import AzureOpenAI

from app import fatf
from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> AzureOpenAI:
    if not settings.azure_foundry_endpoint:
        raise RuntimeError(
            "AZURE_FOUNDRY_ENDPOINT non configurato: imposta l'endpoint Foundry "
            "e la credenziale (dev SP in locale, Workload Identity in prod)."
        )
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), settings.azure_cognitive_scope
    )
    return AzureOpenAI(
        azure_endpoint=settings.azure_foundry_endpoint,
        api_version=settings.azure_openai_api_version,
        azure_ad_token_provider=token_provider,
    )


def _classify_one(client: AzureOpenAI, model: str, text: str) -> dict:
    if not model:
        raise RuntimeError("Deployment LLM non configurato (LLM_MODEL_PRIMARY/SECONDARY).")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": fatf.SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    return fatf.normalize(json.loads(content))


def classify(text: str, *, dual: bool = True) -> dict:
    """Classifica il testo con il modello primario e (se dual) lo valida col
    secondario, riconciliando le categorie e segnalando l'eventuale disaccordo."""
    client = _client()
    text = (text or "")[: settings.max_input_chars]

    primary = _classify_one(client, settings.llm_model_primary, text)
    out = dict(primary)
    out["method"] = "llm_single"
    out["secondary_agreement"] = None
    out["models"] = {"primary": settings.llm_model_primary, "secondary": None}

    if dual and settings.llm_model_secondary:
        secondary = _classify_one(client, settings.llm_model_secondary, text)
        pc, sc = set(primary["fatf_categories"]), set(secondary["fatf_categories"])
        agreement = pc == sc
        # Recall-oriented: in disaccordo si prende l'unione e si segnala (revisione umana).
        out["fatf_categories"] = sorted(pc | sc)
        out["confidence"] = round(
            (primary["confidence"] + secondary["confidence"]) / 2 if agreement
            else min(primary["confidence"], secondary["confidence"]),
            3,
        )
        # severità: prendi la più alta tra i due
        order = {"bassa": 0, "media": 1, "alta": 2}
        out["severity"] = max(primary["severity"], secondary["severity"], key=lambda s: order.get(s, 0))
        out["secondary_agreement"] = agreement
        out["method"] = "llm_dual"
        out["models"]["secondary"] = settings.llm_model_secondary

    return out
