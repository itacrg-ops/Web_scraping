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

import anagraphics
import classifier
import extract as extractor
import fetcher
import mention
import snapshot

LLM_GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:8080")
SVI_PUBLISHER_URL = os.getenv("SVI_PUBLISHER_URL", "http://svi-publisher:8090")
API_BASE = os.getenv("API_BASE", "http://api:8000")
ENTITY_RESOLUTION_URL = os.getenv("ENTITY_RESOLUTION_URL", "http://entity-resolution:8070")
SEARCH_GATEWAY_URL = os.getenv("SEARCH_GATEWAY_URL", "http://search-gateway:8095")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")
# Fallback headless (Playwright) per pagine JS-rendered (B6): default attivo.
HEADLESS_FALLBACK = os.getenv("HEADLESS_FALLBACK", "true").lower() == "true"
# Corroborazione via NER (llm-gateway /v1/ner, B7 parte 2): default attivo, ma
# non fatale — se il modello NER non è installato, il gateway risponde
# available:false e si resta sulla corroborazione a stringhe.
NER_CORROBORATION = os.getenv("NER_CORROBORATION", "true").lower() == "true"


@activity.defn
async def search_articles(subject: dict, options: dict | None = None) -> list[dict]:
    """Ricerca articoli adverse-media per il soggetto via search-gateway
    (provider mock in locale, GDELT keyless in pilota). Non fatale: su
    errore/assenza ritorna lista vuota (la pipeline lo gestisce)."""
    options = options or {}
    payload = {
        # NB: il ruolo NON entra nella ricerca (né PF né PG): è generico e farebbe
        # rumore. Resta usato dalla corroborazione (mention) sul soggetto completo.
        "subject": {k: subject.get(k) for k in
                    ("tipo_soggetto", "denominazione", "nome", "cognome", "cf_piva",
                     "azienda", "localita")},
        "mode": options.get("mode", "targeted"),
        "max_results": options.get("max_results"),
    }
    try:
        # timeout ampio: il gateway può attendere per il throttle/retry di GDELT.
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(f"{SEARCH_GATEWAY_URL}/v1/search", json=payload)
        if resp.status_code == 200:
            data = resp.json()
            activity.logger.info("search_articles: provider=%s count=%s query=%s",
                                 data.get("provider"), data.get("count"), data.get("query"))
            return data.get("results", [])
        activity.logger.warning("search-gateway %s", resp.status_code)
    except Exception as exc:  # noqa: BLE001 — ricerca non disponibile, non fatale
        activity.logger.warning("search-gateway non disponibile (%s)", exc)
    return []


@activity.defn
async def annotate_credibility(urls: list) -> dict:
    """Annota gli URL con dominio + credibilità testata (via search-gateway,
    registro unico). Ritorna {url: {domain, credibilita}}. Non fatale: su
    errore ritorna {} (credibilità sconosciuta → peso neutro nell'AMI)."""
    if not urls:
        return {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{SEARCH_GATEWAY_URL}/v1/credibility", json={"urls": urls})
        if resp.status_code == 200:
            return {
                it["url"]: {"domain": it.get("domain"), "credibilita": it.get("testata_credibilita")}
                for it in resp.json().get("items", [])
            }
        activity.logger.warning("credibility %s", resp.status_code)
    except Exception as exc:  # noqa: BLE001 — non fatale
        activity.logger.warning("annotate_credibility non disponibile (%s)", exc)
    return {}


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
    """Verifica che il soggetto sia citato nell'evidenza (anti falsa attribuzione)
    e corrobora l'identità con i dati anagrafici citati nell'articolo (B7) e con
    la NER (soggetto riconosciuto come persona, azienda come organizzazione)."""
    res = mention.check(subject, text)
    res["anagraphics"] = anagraphics.corroborate(subject, text)
    res["ner"] = await _ner_corroborate(subject, text)
    activity.logger.info("verify_subject_mention: mentioned=%s matched=%s anagrafica=%s ner=%s",
                         res["mentioned"], res["matched"], res["anagraphics"]["status"],
                         (res["ner"] or {}).get("available"))
    return res


def _norm_ent(s: str) -> str:
    return " ".join((s or "").upper().split())


async def _ner_corroborate(subject: dict, text: str) -> dict | None:
    """Chiede la NER al llm-gateway e verifica se il soggetto è riconosciuto come
    PERSONA e l'azienda come ORGANIZZAZIONE. Non fatale: su assenza/errore o NER
    non disponibile ritorna None (resta la corroborazione a stringhe)."""
    if not NER_CORROBORATION or (subject.get("tipo_soggetto") or "persona_giuridica") != "persona_fisica":
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{LLM_GATEWAY_URL}/v1/ner", json={"text": (text or "")[:20000]})
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — non fatale
        activity.logger.info("NER non raggiungibile (%s): corroborazione a stringhe", exc)
        return None
    if not data.get("available"):
        return None

    persons = {_norm_ent(p) for p in data.get("persons", [])}
    orgs = {_norm_ent(o) for o in data.get("orgs", [])}
    nome, cognome = _norm_ent(subject.get("nome")), _norm_ent(subject.get("cognome"))
    subject_person = bool(cognome) and any(
        cognome in p and (not nome or nome in p) for p in persons
    )
    azienda = _norm_ent(subject.get("azienda"))
    azienda_org = bool(azienda) and any(azienda in o or o in azienda for o in orgs)
    return {"available": True, "subject_person": subject_person, "azienda_org": azienda_org,
            "n_persons": len(persons), "n_orgs": len(orgs)}


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
async def render_source(seed_url: str) -> dict:
    """Fallback headless (Playwright) per pagine JS: rende il DOM e lo instrada
    nella STESSA pipeline snapshot/hash/estrazione di `fetch_source`. Gated da
    `HEADLESS_FALLBACK`. Non fatale: se disattivato o su errore ritorna un esito
    SENZA `raw_key`, così il workflow mantiene l'estrazione HTTP originale.
    Il render avviene solo su URL già ammessi da robots/crawl-delay a monte."""
    empty = {"url": seed_url, "allowed": True, "status": None, "final_url": seed_url,
             "content_type": None, "error": None, "raw_key": None, "warc_key": None,
             "content_hash": None, "fetch_ts": None, "bucket": None, "fetch_method": "headless"}
    if not HEADLESS_FALLBACK:
        return {**empty, "error": "headless_disabled", "fetch_method": "headless_disabled"}
    import render as renderer  # import lazy: Playwright è una dipendenza pesante
    res = await renderer.render(seed_url)
    if res.get("error") or not res.get("body"):
        activity.logger.info("Render headless senza contenuto (%s): %s", res.get("error"), seed_url)
        return {**empty, "status": res.get("status"), "final_url": res.get("final_url") or seed_url,
                "error": res.get("error")}
    prov = await asyncio.to_thread(
        snapshot.store, seed_url, res["final_url"], res["status"],
        res["content_type"], res["headers"], res["body"],
    )
    activity.logger.info("Render headless OK %s (%s) hash=%s",
                         res["final_url"], res["status"], prov["content_hash"])
    return {"url": seed_url, "allowed": True, "status": res["status"], "final_url": res["final_url"],
            "content_type": res["content_type"], "error": None, "fetch_method": "headless", **prov}


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


# --- Pesatura AMI: credibilità della fonte e corroborazione (§ scoring) ---
# Fattore per la MIGLIOR credibilità tra le fonti che citano il soggetto.
# "sconosciuta" (testata non ancora nel registro) è una cautela LIEVE, non una
# penalità: distinta da "bassa" (nota come poco affidabile).
# Ordinamento del peso: alta > media > sconosciuta > bassa.
_CRED_WEIGHT = {"alta": 1.05, "media": 1.0, "bassa": 0.8, "sconosciuta": 0.95}
_CRED_ORDER = {"alta": 3, "media": 2, "sconosciuta": 1, "bassa": 0}


def _registrable_domain(url: str) -> str:
    """Dominio registrabile (minuscolo, senza www/sottodomini) per contare le
    fonti indipendenti. Euristica coerente col search-gateway."""
    host = (urlparse(url or "").hostname or "").lower()
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) > 2 else host


def _corroboration_factor(n: int) -> float:
    """Più fonti indipendenti corroborano → più peso; fonte unica: lieve
    cautela; nessuna fonte che cita il soggetto: forte sconto (possibile falsa
    attribuzione)."""
    if n <= 0:
        return 0.5
    return {1: 0.95, 2: 1.0, 3: 1.07}.get(n, 1.15)


@activity.defn
async def compute_ami(subject: dict, classification: dict, evidence_signals: list | None = None) -> dict:
    """Calcolo AMI (placeholder deterministico) pesato per **credibilità** della
    fonte e **corroborazione** (numero di fonti indipendenti che citano il
    soggetto): AMI = base(severità) × credibilità × corroborazione, con cap
    Victim-Bystander. Esplicabile nei driver.

    TODO: materialità(CUP/ruolo), sentiment, freschezza; scoring governato in SAS Viya.
    """
    evidence_signals = evidence_signals or []
    categories = classification.get("fatf_categories", [])
    ruolo = classification.get("ruolo_processuale")
    severity = classification.get("severity")
    role_analysis = classification.get("role_analysis")
    rationale = classification.get("rationale")

    if not categories:
        return {"ami_score": 8, "risk_level": "BASSO", "disposition": "AUTO_CHIUSO",
                "drivers": ["Nessun segnale adverse-media rilevante (early-termination)"]}

    base = {"alta": 88, "media": 68, "bassa": 45}.get(severity, 78)

    # Fonti che citano davvero il soggetto (corroborazione anti falsa attribuzione).
    mentioned = [s for s in evidence_signals if s.get("mentioned")]
    domains = {d for s in mentioned if (d := (s.get("domain") or _registrable_domain(s.get("url", ""))))}
    n_sources = len(domains)
    creds = [(s.get("testata_credibilita") or "sconosciuta") for s in mentioned]
    best_cred = max(creds, key=lambda c: _CRED_ORDER.get(c, 0)) if creds else "sconosciuta"

    f_cred = _CRED_WEIGHT.get(best_cred, 0.75)
    f_corrob = _corroboration_factor(n_sources)
    ami = int(round(base * f_cred * f_corrob))

    # Victim-Bystander Analysis: se il soggetto non è il perpetratore, l'AMI cala.
    if role_analysis in ("vittima", "menzionato"):
        ami = min(ami, 25)
    ami = max(0, min(100, ami))

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
    # Spiegabilità della pesatura AMI.
    if n_sources == 0:
        drivers.append("Corroborazione: nessuna fonte indipendente cita il soggetto "
                       f"(possibile falsa attribuzione) → ×{f_corrob:.2f}")
    else:
        _fonti = "fonte" if n_sources == 1 else "fonti"
        drivers.append(f"Credibilità fonte (migliore su {n_sources} {_fonti}): {best_cred} → ×{f_cred:.2f}")
        if n_sources == 1:
            drivers.append(f"Corroborazione: fonte unica → segnale da confermare (×{f_corrob:.2f})")
        else:
            drivers.append(f"Corroborazione: {n_sources} fonti indipendenti → ×{f_corrob:.2f}")
    drivers.append(f"AMI = base {base} (severità {severity}) × {f_cred:.2f} (credibilità) "
                   f"× {f_corrob:.2f} (corroborazione) = {ami}")
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
    """Persiste l'alert richiamando l'API (sistema di record).

    L'endpoint `POST /api/alerts` è interno: se l'API richiede un token di
    servizio (INTERNAL_API_TOKEN valorizzato), lo inviamo nell'header
    `X-Internal-Token`. In dev il token è vuoto e l'endpoint è aperto.
    """
    headers = {"X-Internal-Token": INTERNAL_API_TOKEN} if INTERNAL_API_TOKEN else None
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{API_BASE}/api/alerts", json=alert_create, headers=headers)
        resp.raise_for_status()
        return resp.json()["id"]
