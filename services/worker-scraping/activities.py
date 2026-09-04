"""Activity della pipeline di screening (walking skeleton).

Le activity fanno l'I/O (fetch, chiamate a llm-gateway / svi-publisher / API).
La logica di dominio è a placeholder (marcata TODO): l'obiettivo qui è avere il
flusso end-to-end collegato. Ogni activity è pensata per essere **idempotente**.
"""
from __future__ import annotations

import os

import httpx
from temporalio import activity

LLM_GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:8080")
SVI_PUBLISHER_URL = os.getenv("SVI_PUBLISHER_URL", "http://svi-publisher:8090")
API_BASE = os.getenv("API_BASE", "http://api:8000")
ENTITY_RESOLUTION_URL = os.getenv("ENTITY_RESOLUTION_URL", "http://entity-resolution:8070")


@activity.defn
async def resolve_entity(subject: dict) -> dict:
    """Gate anti-omonimia: risolve il soggetto contro il registro (§8)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{ENTITY_RESOLUTION_URL}/resolve", json=subject)
        resp.raise_for_status()
        result = resp.json()
    activity.logger.info("resolve_entity: status=%s method=%s conf=%.2f",
                         result.get("status"), result.get("method"), result.get("confidence", 0.0))
    return result


@activity.defn
async def fetch_source(seed_url: str) -> dict:
    """Placeholder: recupero conforme di una pagina/fonte.

    TODO: HTTP client + headless browser, robots.txt/ToS/opt-out TDM, rate
    limiting, snapshot WARC, provenance + marca temporale eIDAS.
    """
    activity.logger.info("fetch_source (stub): %s", seed_url)
    return {"url": seed_url, "status": "stub", "content_hash": "sha256:TODO"}


@activity.defn
async def extract_content(raw: dict) -> dict:
    """Placeholder: boilerplate removal + estrazione testo/metadati."""
    activity.logger.info("extract_content (stub)")
    # Testo demo: consente al resto della pipeline di produrre un alert visibile.
    text = (
        "Sequestro preventivo e indagine per turbativa d'asta a carico "
        "dell'impresa esecutrice; ipotesi di frode nell'affidamento."
    )
    return {"text": text, "meta": {}, "source": raw.get("url")}


@activity.defn
async def classify_fatf(text: str) -> dict:
    """Classificazione FATF via llm-gateway (Azure Foundry).

    Se il gateway non è configurato (nessuna credenziale Foundry in locale),
    ricade su una classificazione demo, così il walking skeleton funziona
    comunque out-of-the-box.
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{LLM_GATEWAY_URL}/v1/classify", json={"text": text, "dual": True})
        if resp.status_code == 200:
            # TODO: parsing strutturato dell'output del modello (JSON FATF).
            activity.logger.info("classify_fatf: risposta dal gateway LLM")
            return {
                "fatf_categories": ["Fraud & Financial Crime", "Corruption & Bribery"],
                "ruolo_processuale": "indagine_preliminare",
                "confidence": 0.8,
                "raw": resp.json(),
            }
        activity.logger.warning("llm-gateway ha risposto %s: uso classificazione demo", resp.status_code)
    except Exception as exc:  # noqa: BLE001
        activity.logger.warning("llm-gateway non raggiungibile (%s): uso classificazione demo", exc)

    return {
        "fatf_categories": ["Fraud & Financial Crime", "Corruption & Bribery"],
        "ruolo_processuale": "indagine_preliminare",
        "confidence": 0.5,
        "raw": None,
    }


@activity.defn
async def compute_ami(subject: dict, classification: dict) -> dict:
    """Calcolo AMI (placeholder deterministico).

    TODO: severità × materialità(CUP/ruolo) × sentiment × credibilità ×
    freschezza × corroborazione × ruolo processuale; scoring governato in SAS Viya.
    """
    categories = classification.get("fatf_categories", [])
    has_signal = bool(categories)
    ami = 82 if has_signal else 10
    risk = "ALTO" if has_signal else "BASSO"
    disposition = "ESCALATION_I_LIVELLO" if has_signal else "AUTO_CHIUSO"
    drivers = (
        [
            "Bad news su UBO/impresa: indagine per turbativa d'asta",
            "Materialità rispetto al CUP dell'intervento",
        ]
        if has_signal
        else ["Nessun segnale rilevante (early-termination)"]
    )
    return {"ami_score": ami, "risk_level": risk, "disposition": disposition, "drivers": drivers}


@activity.defn
async def publish_svi(alert_payload: dict) -> str:
    """Pubblica l'alert in SAS Visual Investigator (mock in locale)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{SVI_PUBLISHER_URL}/publish/alert", json=alert_payload)
        resp.raise_for_status()
        return resp.json()["svi_alert_id"]


@activity.defn
async def persist_alert(alert_create: dict) -> str:
    """Persiste l'alert richiamando l'API (sistema di record)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{API_BASE}/api/alerts", json=alert_create)
        resp.raise_for_status()
        return resp.json()["id"]
