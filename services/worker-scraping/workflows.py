"""Workflow di screening (walking skeleton) con gate di Entity Resolution.

Orchestrazione durevole con Temporal:
  Entity Resolution (gate) → [se superata] web search (o URL forniti) →
  per ogni articolo: fetch → extract → verifica di menzione → classify FATF
  (sul testo aggregato) → AMI → pubblicazione SVI → persistenza (un alert con
  più evidenze).
Gli URL da screenare si scelgono in quest'ordine: `seed_url` singolo (override
manuale) → `seed_urls` (candidati scelti in console) → ricerca automatica via
search-gateway. Se il gate NON è superato (soggetto ambiguo/irrisolto), NON si
produce alcun giudizio: si persiste un esito "da disambiguare" per la revisione
umana (abstain by default).
"""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import (
        classify_fatf,
        compute_ami,
        extract_content,
        fetch_source,
        persist_alert,
        publish_svi,
        resolve_entity,
        search_articles,
        verify_subject_mention,
    )

_RETRY = RetryPolicy(maximum_attempts=3)
_TIMEOUT = timedelta(seconds=60)

_DEFAULT_MAX_ARTICLES = 3      # quanti articoli screenare al massimo in modalità auto
_MAX_CLASSIFY_CHARS = 12000    # cap del testo aggregato inviato alla classificazione


@workflow.defn
class ScreeningWorkflow:
    @workflow.run
    async def run(self, req: dict) -> dict:
        subject = {
            "tipo_soggetto": req.get("tipo_soggetto", "persona_giuridica"),
            "denominazione": req["denominazione"],
            "nome": req.get("nome"),
            "cognome": req.get("cognome"),
            "data_nascita": req.get("data_nascita"),
            "cf_piva": req.get("cf_piva"),
            "cup": req.get("cup", []),
        }

        # --- GATE: Entity Resolution (obbligatoria prima del giudizio) ---
        resolution = await workflow.execute_activity(
            resolve_entity, subject, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )

        if not resolution.get("resolved"):
            # Abstain by default: nessun giudizio, escalation alla disambiguazione umana.
            held = {
                "screening_id": req["screening_id"],
                "subject": subject["denominazione"],
                "tipo_soggetto": subject["tipo_soggetto"],
                "cf_piva": subject["cf_piva"],
                "cup": subject["cup"],
                "ami_score": 0,
                "risk_level": "N/D",
                "fatf_categories": [],
                "drivers": ["Entity Resolution non superata: richiede disambiguazione umana"],
                "disposition": "HITL_ENTITY_RESOLUTION",
                "svi_alert_id": None,
                "entity_resolution": resolution,
            }
            alert_id = await workflow.execute_activity(
                persist_alert, held, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
            )
            return {"alert_id": alert_id, "gate": resolution.get("status"), "resolved": False}

        # Soggetto disambiguato: arricchisco con l'identità risolta.
        matched = resolution.get("matched") or {}
        if matched.get("cup"):
            subject["cup"] = subject["cup"] or matched.get("cup", [])

        # --- Selezione degli URL da screenare ---
        # Precedenza: seed_url singolo (override) → seed_urls (candidati scelti in
        # console) → ricerca automatica via search-gateway (web search).
        max_articles = int(req.get("max_articles") or _DEFAULT_MAX_ARTICLES)
        search_drivers: list[str] = []
        cred_by_url: dict = {}  # url → credibilità testata (dalla web search)
        if req.get("seed_url"):
            urls = [req["seed_url"]]
        elif req.get("seed_urls"):
            urls = list(req["seed_urls"])[:max_articles]
            search_drivers.append(f"Screening su {len(urls)} articoli selezionati in console")
        else:
            results = await workflow.execute_activity(
                search_articles, args=[subject, {"mode": "targeted", "max_results": max_articles}],
                start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
            )
            urls = [r["url"] for r in results if r.get("url")][:max_articles]
            cred_by_url = {r["url"]: r.get("testata_credibilita") for r in results if r.get("url")}
            search_drivers.append(f"Web search: {len(urls)} articoli candidati analizzati")

        # --- Fetch + estrazione + verifica di menzione per ciascun URL ---
        docs: list[dict] = []
        any_mention = False
        for url in urls:
            raw = await workflow.execute_activity(
                fetch_source, url, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
            )
            doc = await workflow.execute_activity(
                extract_content, raw, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
            )
            men = await workflow.execute_activity(
                verify_subject_mention, args=[subject, doc.get("text", "")],
                start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
            )
            doc["_mentioned"] = bool(men.get("mentioned"))
            doc["_credibilita"] = cred_by_url.get(url)
            any_mention = any_mention or doc["_mentioned"]
            docs.append(doc)

        # Testo per la classificazione: preferisci gli articoli che citano il
        # soggetto; se nessuno lo cita, usa tutti quelli con contenuto (con warning).
        with_text = [d for d in docs if d.get("text")]
        screening_docs = [d for d in with_text if d.get("_mentioned")] or with_text
        combined = "\n\n".join(d["text"] for d in screening_docs)[:_MAX_CLASSIFY_CHARS]

        if combined:
            classification = await workflow.execute_activity(
                classify_fatf, combined, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
            )
        else:
            classification = {"fatf_categories": [], "method": "nessun_contenuto"}

        ami = await workflow.execute_activity(
            compute_ami, args=[subject, classification],
            start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
        )

        drivers = search_drivers + list(ami["drivers"])
        if not urls:
            drivers.insert(0, "Nessun articolo trovato dalla ricerca (web search)")
        elif not any_mention:
            drivers.insert(
                0,
                "⚠ Soggetto non citato negli articoli analizzati: verificare attribuzione (possibile falsa attribuzione)",
            )

        alert_payload = {
            "subject": subject["denominazione"],
            "tipo_soggetto": subject["tipo_soggetto"],
            "cf_piva": subject["cf_piva"],
            "cup": subject["cup"],
            "ami_score": ami["ami_score"],
            "risk_level": ami["risk_level"],
            "fatf_categories": classification.get("fatf_categories", []),
            "drivers": drivers,
            "disposition": ami["disposition"],
        }

        svi_alert_id = await workflow.execute_activity(
            publish_svi, alert_payload, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )

        # Evidenze ancorate all'alert (una per articolo effettivamente recuperato
        # e con hash: URL, snippet, hash, timestamp, WARC).
        evidence = []
        for d in docs:
            prov = d.get("provenance") or {}
            if not prov.get("content_hash"):
                continue
            text = d.get("text") or ""
            evidence.append({
                "url": d.get("source"),
                "testata": d.get("testata"),
                "title": d.get("title"),
                "data": d.get("date"),
                "snippet": text[:300],
                "content_hash": prov.get("content_hash"),
                "fetch_ts": prov.get("fetch_ts"),
                "bucket": prov.get("bucket"),
                "raw_key": prov.get("raw_key"),
                "warc_key": prov.get("warc_key"),
                "fonte_credibilita": d.get("_credibilita"),
            })

        alert_create = {
            **alert_payload,
            "screening_id": req["screening_id"],
            "svi_alert_id": svi_alert_id,
            "entity_resolution": resolution,
            "evidence": evidence,
        }
        alert_id = await workflow.execute_activity(
            persist_alert, alert_create, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )

        return {
            "alert_id": alert_id,
            "svi_alert_id": svi_alert_id,
            "ami_score": ami["ami_score"],
            "articles": len(docs),
            "resolved": True,
        }
