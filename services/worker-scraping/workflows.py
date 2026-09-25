"""Workflow di screening (walking skeleton) con gate di Entity Resolution.

Orchestrazione durevole con Temporal:
  Entity Resolution (gate) → [se superata] web search (o URL forniti) →
  per ogni articolo: fetch → extract → verifica di menzione → classify FATF
  (sul testo aggregato) → AMI → persistenza (un alert con più evidenze, PRIMA di
  SVI) → pubblicazione SVI → esito della pubblicazione registrato sull'alert.
Guasti (ricerca, contenuti, LLM, feed di rischio) → esito ESITO_INCOMPLETO, mai
AUTO_CHIUSO; un errore non gestito segna lo screening come `failed`.
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
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from activities import (
        annotate_credibility,
        assess_risk_feed,
        classify_fatf,
        compute_ami,
        extract_content,
        fetch_source,
        mark_screening_failed,
        persist_alert,
        publish_svi,
        render_source,
        resolve_entity,
        search_articles,
        update_alert_svi,
        verify_subject_mention,
    )
    from analysis import ami_signals, classification_text, merge_risk_feed, saved_classification
    from outcome import apply_incomplete, incomplete_reasons
    from replay import replay_dataset, replay_failed
    from roles import is_pep, summarize as summarize_roles

_RETRY = RetryPolicy(maximum_attempts=3)
_TIMEOUT = timedelta(seconds=60)
# Pubblicazione SVI: > SVI_PUBLISH_TIMEOUT del worker (120s) > SVI_PUBLISH_DEADLINE del
# publisher (90s). Se fosse più corto, Temporal ritenterebbe mentre la prima
# pubblicazione è ancora in corso.
_SVI_TIMEOUT = timedelta(seconds=180)

_DEFAULT_MAX_ARTICLES = 3      # quanti articoli screenare al massimo in modalità auto
_HEADLESS_TIMEOUT = timedelta(seconds=90)  # il render JS è più lento del fetch HTTP
_HEADLESS_MIN_CHARS = 400      # sotto questa soglia l'estrazione è "povera" → prova headless
_RENDER_RETRY = RetryPolicy(maximum_attempts=2)  # render costoso: meno tentativi
# Rivalutazione del dataset: un'unica activity lunga (decine di casi, LLM per ognuno),
# viva finché segnala l'avanzamento; non si ripete da sola (costi LLM, report doppio).
_REPLAY_TIMEOUT = timedelta(hours=6)
_REPLAY_HEARTBEAT = timedelta(minutes=10)


def _cause(exc: BaseException) -> str:
    """Messaggio leggibile di un errore d'activity (la causa reale sta in `cause`)."""
    while isinstance(exc, ActivityError) and exc.cause is not None:
        exc = exc.cause
    return (getattr(exc, "message", None) or str(exc) or type(exc).__name__)[:500]


@workflow.defn
class ScreeningWorkflow:
    @workflow.run
    async def run(self, req: dict) -> dict:
        try:
            return await self._screen(req)
        except Exception as exc:
            # Lo screening non deve restare "running" per sempre: registra il motivo
            # (best effort) e rilancia, così Temporal mostra comunque l'errore.
            try:
                await workflow.execute_activity(
                    mark_screening_failed, args=[req.get("screening_id"), _cause(exc)],
                    start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
                )
            except Exception:  # noqa: BLE001 — l'errore da mostrare è quello originale
                workflow.logger.warning("impossibile segnare lo screening come fallito")
            raise

    async def _screen(self, req: dict) -> dict:
        subject = {
            "tipo_soggetto": req.get("tipo_soggetto", "persona_giuridica"),
            "denominazione": req["denominazione"],
            "nome": req.get("nome"),
            "cognome": req.get("cognome"),
            "data_nascita": req.get("data_nascita"),
            "luogo_nascita": req.get("luogo_nascita"),
            "cf_piva": req.get("cf_piva"),
            # Qualificatori persona fisica: azienda/località (query in AND) e ruolo (soft).
            "azienda": req.get("azienda"),
            "localita": req.get("localita"),
            "ruolo": req.get("ruolo"),
            "cup": req.get("cup", []),
            # soggetto del registro indicato dal revisore (caso «Da disambiguare»)
            "subject_id": req.get("subject_id"),
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
                "svi_status": "skipped",   # non pubblicato in SVI per scelta (abstain)
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

        # --- Feed di rischio strutturato (AML/CFT) sul soggetto RISOLTO ---
        # Dopo il gate anti-omonimia: l'identità è certa, quindi ha senso
        # interrogare un feed per identità (Crime&tech). Default OFF (RISK_PROVIDER
        # vuoto) → None → nessun arricchimento. Non altera il percorso articoli.
        risk_feed = await workflow.execute_activity(
            assess_risk_feed, subject, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )

        # --- Selezione degli URL da screenare ---
        # Precedenza: seed_url singolo (override) → seed_urls (candidati scelti in
        # console) → ricerca automatica via search-gateway (web search).
        max_articles = int(req.get("max_articles") or _DEFAULT_MAX_ARTICLES)
        search_drivers: list[str] = []
        search_error: str | None = None
        if req.get("seed_url"):
            urls = [req["seed_url"]]
        elif req.get("seed_urls"):
            urls = list(req["seed_urls"])[:max_articles]
            search_drivers.append(f"Screening su {len(urls)} articoli selezionati in console")
        else:
            try:
                results = await workflow.execute_activity(
                    search_articles, args=[subject, {"mode": "targeted", "max_results": max_articles}],
                    start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
                )
            except ActivityError as err:
                # Guasto della ricerca ≠ "nessun articolo": esito INCOMPLETO (vedi sotto).
                results, search_error = [], _cause(err)
            urls = [r["url"] for r in results if r.get("url")][:max_articles]
            if search_error is None:
                search_drivers.append(f"Web search: {len(urls)} articoli candidati analizzati")

        # Credibilità delle testate (registro unico via search-gateway), uniforme
        # su tutti i percorsi: pesa l'AMI e annota l'evidenza.
        cred_map = (
            await workflow.execute_activity(
                annotate_credibility, urls, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
            )
            if urls else {}
        )

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
            # Fallback headless (B6): estrazione povera → probabile pagina JS-rendered.
            # Rendo il DOM con Playwright e ri-estraggo; tengo la versione con più testo.
            if raw.get("allowed") and len(doc.get("text") or "") < _HEADLESS_MIN_CHARS:
                raw_r = await workflow.execute_activity(
                    render_source, url,
                    start_to_close_timeout=_HEADLESS_TIMEOUT, retry_policy=_RENDER_RETRY,
                )
                if raw_r.get("raw_key"):
                    doc_r = await workflow.execute_activity(
                        extract_content, raw_r, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
                    )
                    if len(doc_r.get("text") or "") > len(doc.get("text") or ""):
                        raw, doc = raw_r, doc_r
                        doc["_fetch_method"] = "headless"
            men = await workflow.execute_activity(
                verify_subject_mention, args=[subject, doc.get("text", "")],
                start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
            )
            info = cred_map.get(url) or {}
            doc["_mentioned"] = bool(men.get("mentioned"))
            doc["_matched"] = men.get("matched", [])
            doc["_context"] = men.get("context", [])
            doc["_anagraphics"] = men.get("anagraphics") or {"status": "n/a"}
            doc["_variants"] = men.get("variants") or []
            doc["_roles"] = men.get("roles") or []
            doc["_ner"] = men.get("ner")
            doc["_credibilita"] = info.get("credibilita")
            doc["_domain"] = info.get("domain")
            any_mention = any_mention or doc["_mentioned"]
            docs.append(doc)

        # Testo per la classificazione: preferisci gli articoli che citano il
        # soggetto; se nessuno lo cita, usa tutti quelli con contenuto (con warning).
        # Logica condivisa con la rivalutazione del dataset (analysis.py).
        with_text = [d for d in docs if d.get("text")]
        combined = classification_text(docs)

        if combined:
            classification = await workflow.execute_activity(
                classify_fatf,
                args=[combined, subject["denominazione"], subject["tipo_soggetto"] == "persona_fisica"],
                start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
            )
        else:
            classification = {"fatf_categories": [], "method": "nessun_contenuto"}

        # Feed di rischio strutturato: se disponibile, fonde categorie FATF e
        # severità nella classificazione PRIMA dell'AMI (un riscontro dal feed
        # pesa anche quando gli articoli tacciono). Default OFF → nessun effetto.
        risk_available = bool(risk_feed and risk_feed.get("available"))
        if risk_available:
            classification = merge_risk_feed(classification, risk_feed)

        # Segnali per la pesatura AMI: per ogni articolo, fonte + credibilità +
        # se cita il soggetto (corroborazione da fonti indipendenti).
        ami = await workflow.execute_activity(
            compute_ami, args=[subject, classification, ami_signals(docs)],
            start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
        )

        drivers = search_drivers + list(ami["drivers"])
        if any(d.get("_fetch_method") == "headless" for d in docs):
            drivers.append("Alcune fonti JS-rendered recuperate con browser headless")
        n_missing = len(urls) - len(with_text)
        if 0 < n_missing < len(urls):
            drivers.append(f"{n_missing} fonti su {len(urls)} non recuperate (robots.txt, paywall "
                           "o errori di rete): analisi parziale")
        if not urls:
            if search_error is None:  # ricerca riuscita ma vuota (il guasto è gestito sotto)
                drivers.insert(0, "Nessun articolo trovato dalla ricerca (web search)")
        elif not any_mention:
            drivers.insert(
                0,
                "⚠ Soggetto non citato negli articoli analizzati: verificare attribuzione (possibile falsa attribuzione)",
            )
        # Il nome esatto non c'è ma c'è un nome molto simile («Andrea Stroppa» per
        # «Stropp Andrea»): probabile refuso nel nome inserito. Solo un'indicazione.
        name_variants = [] if any_mention else list(dict.fromkeys(
            v for d in docs for v in d.get("_variants") or []))[:5]
        if name_variants:
            drivers.insert(0, "⚠ Negli articoli compare un nome simile: "
                           + ", ".join(f"«{v}»" for v in name_variants)
                           + " — il nome del soggetto potrebbe contenere un refuso: verificarlo")

        # Ruoli della persona scritti accanto al nome negli articoli che la citano:
        # cariche pubbliche/politiche (possibile PEP) e ruoli aziendali (AD, DG, CEO…).
        # Il flag PEP non cambia l'AMI: è un'informazione per l'analista.
        found_roles = summarize_roles([d.get("_roles") or [] for d in docs if d.get("_mentioned")])
        pep = is_pep(found_roles)
        if found_roles:
            drivers.append("Ruoli negli articoli: " + "; ".join(
                r["ruolo"] + (f" ({r['articoli']} articoli)" if r["articoli"] > 1 else "") for r in found_roles))
        if pep:
            peps = [r for r in found_roles if r.get("pep")]
            notes = []
            if any(r["tipo"] == "sindaco" for r in peps):
                notes.append("per il sindaco: capoluogo o comune con almeno 15.000 abitanti")
            if any(r["ex"] for r in peps):
                notes.append("carica cessata: PEP fino a un anno dalla cessazione")
            drivers.insert(0, "⚠ Possibile PEP (persona politicamente esposta, D.Lgs. 231/2007): "
                           + ", ".join(r["ruolo"] for r in peps) + " — da verificare"
                           + (f" ({'; '.join(notes)})" if notes else ""))

        # Corroborazione del contesto (persona fisica): azienda/località/ruolo
        # riscontrati negli articoli che citano il soggetto → riduce l'omonimia;
        # altrimenti segnala "possibile omonimo".
        _qual_keys = ("azienda", "localita", "ruolo")
        _labels = {"azienda": "azienda", "localita": "località", "ruolo": "ruolo"}
        has_quals = subject["tipo_soggetto"] == "persona_fisica" and any(subject.get(k) for k in _qual_keys)
        if has_quals and any_mention:
            context_hits = sorted({c for d in docs if d.get("_mentioned") for c in (d.get("_context") or [])})
            if context_hits:
                drivers.insert(0, "Contesto confermato negli articoli ("
                               + ", ".join(_labels.get(c, c) for c in context_hits)
                               + "): probabilità di omonimia ridotta")
            else:
                drivers.insert(0, "⚠ Contesto (azienda/località/ruolo) non riscontrato negli articoli "
                               "citanti: possibile omonimo, verificare l'identità")

        # Corroborazione anagrafica dagli articoli (persona fisica): età/anno/luogo
        # di nascita citati coerenti o discordanti col soggetto → mitiga l'omonimia.
        if subject["tipo_soggetto"] == "persona_fisica" and any_mention:
            _ana = [d.get("_anagraphics") or {} for d in docs if d.get("_mentioned")]
            _disc = [f for a in _ana if a.get("status") == "discordante" for f in a.get("findings", [])]
            _conf = [f for a in _ana if a.get("status") == "confermato" for f in a.get("findings", [])]
            if _disc:
                drivers.insert(0, "⚠ Dati anagrafici discordanti negli articoli ("
                               + "; ".join(sorted(set(_disc))) + "): possibile OMONIMO, verificare l'identità")
            elif _conf:
                drivers.insert(0, "Dati anagrafici confermati negli articoli ("
                               + "; ".join(sorted(set(_conf))) + "): identità corroborata")

            # Corroborazione via NER (B7 parte 2): soggetto riconosciuto come
            # persona, azienda come organizzazione negli articoli.
            _ner = [d.get("_ner") for d in docs if d.get("_mentioned") and d.get("_ner")]
            if any(n.get("azienda_org") for n in _ner):
                drivers.insert(0, "NER: azienda riconosciuta come organizzazione negli articoli — "
                               "corroborazione rafforzata")
            elif any(n.get("subject_person") for n in _ner):
                drivers.insert(0, "NER: soggetto riconosciuto come persona negli articoli")

        if resolution.get("status") == "provvisorio":
            drivers.insert(
                0,
                "⚠ Screening ESPLORATIVO: soggetto non a registro — identità e pertinenza al CUP da verificare",
            )

        # Feed di rischio: blocco di driver in testa se c'è un riscontro; una nota
        # di trasparenza se il feed è attivo ma senza riscontro utilizzabile.
        if risk_available:
            block = [f"— Feed di rischio ({risk_feed.get('provider')}) —"] + list(risk_feed.get("drivers", []))
            drivers = block + drivers
        elif risk_feed is not None and not risk_feed.get("error"):
            drivers.append(
                f"Feed di rischio ({risk_feed.get('provider')}): nessun riscontro utilizzabile "
                f"({risk_feed.get('reason')})"
            )

        # Pipeline degradata (ricerca fallita, nessun contenuto, LLM o feed di rischio
        # non disponibili) → ESITO_INCOMPLETO: mai AUTO_CHIUSO né escalation automatica.
        outcome = apply_incomplete(
            {"ami_score": ami["ami_score"], "risk_level": ami["risk_level"],
             "disposition": ami["disposition"], "drivers": drivers},
            incomplete_reasons(search_error=search_error, urls=urls, docs_with_text=len(with_text),
                               classification=classification, risk_feed=risk_feed),
        )

        alert_payload = {
            "subject": subject["denominazione"],
            "tipo_soggetto": subject["tipo_soggetto"],
            "cf_piva": subject["cf_piva"],
            "cup": subject["cup"],
            "ami_score": outcome["ami_score"],
            "risk_level": outcome["risk_level"],
            "fatf_categories": classification.get("fatf_categories", []),
            "drivers": outcome["drivers"],
            "disposition": outcome["disposition"],
            "name_variants": name_variants,
            "roles": found_roles,
            "pep": pep if subject["tipo_soggetto"] == "persona_fisica" else None,
        }

        # Evidenze ancorate all'alert (una per articolo effettivamente recuperato
        # e con hash: URL, snippet, hash, timestamp, WARC). Costruite PRIMA della
        # pubblicazione così SVI riceve alert + evidenze insieme (B2).
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
                # predizione del sistema, confrontata poi con le etichette dei revisori
                "mentioned": d.get("_mentioned"),
                "mention_match": d.get("_matched") or [],
            })

        # 1) Salva PRIMA in locale (sistema di record; idempotente per screening): un
        #    guasto di SVI non fa più perdere il risultato dello screening.
        alert_id = await workflow.execute_activity(
            persist_alert,
            {**alert_payload, "screening_id": req["screening_id"], "svi_status": "pending",
             "entity_resolution": resolution, "evidence": evidence,
             "classification": saved_classification(classification)},
            start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
        )

        # 2) Pubblica in SVI (B2): motivazione + evidenze + screening_id (business key:
        #    nessun duplicato su retry). Un fallimento resta registrato sull'alert.
        svi_alert_id: str | None = None
        try:
            svi_alert_id = await workflow.execute_activity(
                publish_svi, {**alert_payload, "screening_id": req["screening_id"], "evidence": evidence},
                start_to_close_timeout=_SVI_TIMEOUT, retry_policy=_RETRY,
            )
            svi_update = {"svi_status": "published", "svi_alert_id": svi_alert_id}
        except ActivityError as err:
            svi_update = {"svi_status": "failed", "svi_error": _cause(err)}

        # 3) Esito della pubblicazione sull'alert.
        await workflow.execute_activity(
            update_alert_svi, args=[alert_id, svi_update],
            start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
        )

        return {
            "alert_id": alert_id,
            "svi_alert_id": svi_alert_id,
            "svi_status": svi_update["svi_status"],
            "ami_score": outcome["ami_score"],
            "disposition": outcome["disposition"],
            "articles": len(docs),
            "resolved": True,
        }


@workflow.defn
class ReplayWorkflow:
    """Rivalutazione del dataset etichettato avviata dalla console (pagina
    Observability): i casi ripassati nella versione attuale del sistema; il report lo
    calcola l'API. Se si ferma, il motivo resta sulla rivalutazione."""

    @workflow.run
    async def run(self, req: dict) -> dict:
        try:
            return await workflow.execute_activity(
                replay_dataset, args=[req["run_id"], req.get("solo_affidabili", True)],
                start_to_close_timeout=_REPLAY_TIMEOUT, heartbeat_timeout=_REPLAY_HEARTBEAT,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError as err:
            await workflow.execute_activity(
                replay_failed, args=[req["run_id"], _cause(err)],
                start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY,
            )
            raise
