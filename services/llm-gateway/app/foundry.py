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

from app import fatf, ner, pii
from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> AzureOpenAI:
    if not settings.azure_foundry_endpoint:
        raise RuntimeError(
            "AZURE_FOUNDRY_ENDPOINT non configurato: imposta l'endpoint Foundry "
            "e la credenziale (API key oppure Entra: dev SP in locale / Workload Identity in prod)."
        )
    # Modalità A — API key (endpoint + key): ha la precedenza se valorizzata.
    if settings.azure_api_key:
        return AzureOpenAI(
            azure_endpoint=settings.azure_foundry_endpoint,
            api_version=settings.azure_openai_api_version,
            api_key=settings.azure_api_key,
        )
    # Modalità B — keyless (Entra) via DefaultAzureCredential.
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), settings.azure_cognitive_scope
    )
    return AzureOpenAI(
        azure_endpoint=settings.azure_foundry_endpoint,
        api_version=settings.azure_openai_api_version,
        azure_ad_token_provider=token_provider,
    )


def embed(texts: list[str]) -> dict:
    """Embedding dei testi via Azure AI Foundry (deployment `embedding_model`).
    Usato dall'Entity Resolution per la similarità semantica dei nomi (B7).
    Applica la redazione PII per coerenza col resto del gateway (i nomi propri
    passano: la redazione MVP tocca solo gli identificatori strutturati)."""
    if not settings.embedding_model:
        raise RuntimeError(
            "EMBEDDING_MODEL non configurato: imposta il deployment di embedding su Foundry."
        )
    client = _client()
    cleaned: list[str] = []
    redacted_total = 0
    for t in texts:
        s = t or ""
        if settings.pii_redaction:
            s, rep = pii.redact(s)
            redacted_total += rep["total"]
        cleaned.append(s[: settings.max_input_chars])
    if redacted_total:
        logger.info("PII redatte prima dell'embedding: %d", redacted_total)
    resp = client.embeddings.create(model=settings.embedding_model, input=cleaned)
    vectors = [list(d.embedding) for d in resp.data]
    return {"model": settings.embedding_model,
            "dims": len(vectors[0]) if vectors else 0,
            "embeddings": vectors}


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


def classify(text: str, *, subject_name: str | None = None,
             subject_person: bool = False, dual: bool = True) -> dict:
    """Classifica il testo con il modello primario e (se dual) lo valida col
    secondario, riconciliando le categorie e segnalando l'eventuale disaccordo.
    `subject_name`/`subject_person`: se il soggetto è una persona, il suo nome è
    pseudonimizzato in `[SOGGETTO]` (B1.1)."""
    client = _client()

    # Redazione PII PRIMA di qualunque invio ad Azure (unico chokepoint di egress).
    # Si redige il testo completo e poi si tronca, così non si spezza un token PII
    # sul confine del cap.
    redaction = {"total": 0, "by_category": {}}
    names = {"soggetto": 0, "persona": 0}
    raw = text or ""
    if settings.pii_redaction:
        raw, redaction = pii.redact(raw)
        # B1.1: redazione dei NOMI di persona (soggetto → [SOGGETTO], terzi → [PERSONA])
        # via NER; il nome del soggetto (noto) è redatto anche senza NER.
        if settings.redact_person_names:
            persons = ner.extract(raw).get("persons", [])
            raw, names = pii.redact_persons(
                raw, subject_name if subject_person else None, persons
            )
        if redaction["total"] or names["soggetto"] or names["persona"]:
            logger.info("PII redatte prima dell'LLM: strutturate=%s, nomi=%s",
                        redaction["by_category"], names)
    text = raw[: settings.max_input_chars]
    # Marcatore per l'analisi del ruolo (Victim-Bystander): il soggetto è [SOGGETTO].
    if names["soggetto"]:
        text = "Nota: il soggetto in esame è indicato nel testo come [SOGGETTO].\n\n" + text

    primary = _classify_one(client, settings.llm_model_primary, text)
    out = dict(primary)
    out["method"] = "llm_single"
    out["secondary_agreement"] = None
    out["models"] = {"primary": settings.llm_model_primary, "secondary": None}
    out["pii_redaction"] = {**redaction, "names": names}

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
