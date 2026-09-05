"""Activity della pipeline di screening (walking skeleton).

Le activity fanno l'I/O (fetch, chiamate a llm-gateway / svi-publisher / API).
La logica di dominio è a placeholder (marcata TODO): l'obiettivo qui è avere il
flusso end-to-end collegato. Ogni activity è pensata per essere **idempotente**.
"""
from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import httpx
from temporalio import activity

import classifier
import extract as extractor
import fetcher
import mention
import snapshot

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
async def verify_subject_mention(subject: dict, text: str) -> dict:
    """Verifica che il soggetto sia citato nell'evidenza (anti falsa attribuzione)."""
    res = mention.check(subject, text)
    activity.logger.info("verify_subject_mention: mentioned=%s matched=%s",
                         res["mentioned"], res["matched"])
    return res


@activity.defn
async def fetch_source(seed_url: str) -> dict:
    """Fetch conforme: robots.txt/crawl-delay, snapshot WARC su object store,
    hash SHA-256 e provenance. Non fatale: su blocco/errore ritorna un esito
    strutturato (la pipeline prosegue con contenuto vuoto)."""
    res = await fetcher.fetch(seed_url)
    if not res["allowed"]:
        activity.logger.warning("Fetch bloccato da robots.txt: %s", seed_url)
        return {"url": seed_url, "allowed": False, "status": None, "error": res.get("error"),
                "final_url": res.get("final_url"), "raw_key": None, "warc_key": None,
                "content_hash": None, "fetch_ts": None}
    if res.get("error") or not res.get("body"):
        activity.logger.warning("Fetch senza contenuto (%s): %s", res.get("error"), seed_url)
        return {"url": seed_url, "allowed": True, "status": res.get("status"), "error": res.get("error"),
                "final_url": res.get("final_url"), "raw_key": None, "warc_key": None,
                "content_hash": None, "fetch_ts": None}
    prov = await asyncio.to_thread(
        snapshot.store, seed_url, res["final_url"], res["status"],
        res["content_type"], res["headers"], res["body"],
    )
    activity.logger.info("Fetch OK %s (%s) hash=%s", res["final_url"], res["status"], prov["content_hash"])
    return {"url": seed_url, "allowed": True, "status": res["status"], "final_url": res["final_url"],
            "content_type": res["content_type"], "error": None, **prov}


@activity.defn
async def extract_content(raw: dict) -> dict:
    """Estrazione testo/metadati dallo snapshot (trafilatura)."""
    src = raw.get("final_url") or raw.get("url")
    testata = urlparse(src or "").netloc
    if not raw.get("raw_key"):
        return {"text": "", "title": None, "date": None, "author": None,
                "source": src, "testata": testata,
                "provenance": {"error": raw.get("error"), "allowed": raw.get("allowed")}}
    html = await asyncio.to_thread(snapshot.load_html, raw["bucket"], raw["raw_key"])
    meta = await asyncio.to_thread(extractor.extract, html, src)
    activity.logger.info("Estratti %d caratteri di testo", len(meta.get("text") or ""))
    return {
        "text": meta.get("text", ""),
        "title": meta.get("title"),
        "date": meta.get("date"),
        "author": meta.get("author"),
        "source": src,
        "testata": testata,
        "provenance": {
            "content_hash": raw.get("content_hash"),
            "fetch_ts": raw.get("fetch_ts"),
            "warc_key": raw.get("warc_key"),
            "raw_key": raw.get("raw_key"),
            "bucket": raw.get("bucket"),
        },
    }


@activity.defn
async def classify_fatf(text: str) -> dict:
    """Classificazione FATF strutturata via llm-gateway (dual-LLM su Foundry:
    categorie, ruolo processuale, Victim-Bystander, severità, confidence,
    motivazione). Fallback onesto all'euristica a keyword se il gateway non è
    configurato/raggiungibile."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{LLM_GATEWAY_URL}/v1/classify", json={"text": text, "dual": True})
        if resp.status_code == 200:
            data = resp.json()
            data.setdefault("method", "llm")
            activity.logger.info("classify_fatf via LLM: %s (%s)", data.get("fatf_categories"), data.get("method"))
            return data
        activity.logger.info("llm-gateway %s: categorie via euristica", resp.status_code)
    except Exception as exc:  # noqa: BLE001
        activity.logger.info("llm-gateway non disponibile (%s): categorie via euristica", exc)

    return classifier.classify_text(text)


@activity.defn
async def compute_ami(subject: dict, classification: dict) -> dict:
    """Calcolo AMI (placeholder deterministico).

    TODO: severità × materialità(CUP/ruolo) × sentiment × credibilità ×
    freschezza × corroborazione × ruolo processuale; scoring governato in SAS Viya.
    """
    categories = classification.get("fatf_categories", [])
    ruolo = classification.get("ruolo_processuale")
    severity = classification.get("severity")
    role_analysis = classification.get("role_analysis")
    rationale = classification.get("rationale")

    if not categories:
        return {"ami_score": 8, "risk_level": "BASSO", "disposition": "AUTO_CHIUSO",
                "drivers": ["Nessun segnale adverse-media rilevante (early-termination)"]}

    ami = {"alta": 88, "media": 68, "bassa": 45}.get(severity, 78)
    # Victim-Bystander Analysis: se il soggetto non è il perpetratore, l'AMI cala.
    if role_analysis in ("vittima", "menzionato"):
        ami = min(ami, 25)
    risk = "ALTO" if ami >= 75 else "MEDIO" if ami >= 45 else "BASSO"
    disposition = "ESCALATION_I_LIVELLO" if risk in ("ALTO", "MEDIO") else "AUTO_CHIUSO"

    drivers = [f"Categorie FATF: {', '.join(categories)}"]
    if ruolo:
        drivers.append(f"Ruolo processuale: {ruolo}")
    if role_analysis:
        drivers.append(f"Ruolo del soggetto: {role_analysis}")
    if classification.get("secondary_agreement") is False:
        drivers.append("Disaccordo dual-LLM sulle categorie → revisione consigliata")
    if rationale:
        drivers.append(f"Motivazione: {rationale}")
    drivers.append("Materialità da valutare rispetto al CUP dell'intervento")
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
