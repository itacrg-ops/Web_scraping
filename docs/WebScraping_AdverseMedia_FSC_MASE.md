# Applicazione di Web Scraping per l'Adverse Media Screening
## Beneficiari del Fondo per lo Sviluppo e la Coesione (FSC) — Pilota MASE

> **Documento tecnico-funzionale** · Descrizione dell'applicazione e piano di sviluppo
> Autore: Carmelo Garofalo · Principal Systems Engineer · Settembre 2026
> **Versione: 1.1** — revisione tecnica esperta (adverse media / compliance PA). Le modifiche rispetto alla v1.0 sono elencate nell'[Appendice A — Changelog](#appendice-a--changelog-v10--v11).
> Ambito: interventi FSC di competenza del **MASE**, innesto nel **Sistema Informativo del Monitoraggio (SIM)**

---

## Indice

1. [Obiettivo e scope](#1-obiettivo-e-scope)
2. [Architettura dell'applicazione](#2-architettura-dellapplicazione)
3. [Componenti multi-agente](#3-componenti-multi-agente)
4. [Il modulo di Web Scraping in dettaglio](#4-il-modulo-di-web-scraping-in-dettaglio)
5. [Fonti dati e integrazioni](#5-fonti-dati-e-integrazioni)
6. [Stack tecnologico](#6-stack-tecnologico)
7. [Modello dati e output](#7-modello-dati-e-output)
8. [Governance, conformità e sicurezza](#8-governance-conformità-e-sicurezza)
9. [Piano di sviluppo](#9-piano-di-sviluppo)
10. [Rischi e mitigazioni](#10-rischi-e-mitigazioni)
11. [Criteri di accettazione (Definition of Done)](#11-criteri-di-accettazione-definition-of-done)
- [Appendice A — Changelog v1.0 → v1.1](#appendice-a--changelog-v10--v11)
- [Appendice B — Riferimenti normativi](#appendice-b--riferimenti-normativi)

---

## 1. Obiettivo e scope

### 1.1 Obiettivo
Realizzare un'applicazione che automatizzi lo **screening di notizie negative (adverse media / bad news)** sui beneficiari, soggetti attuatori e imprese esecutrici degli interventi finanziati dal **FSC** di competenza del MASE, producendo alert spiegabili e auditabili a supporto dei **controlli desk (I livello)** del Si.Ge.Co. / SIM.

Lo strumento è un **ausilio istruttorio** (decision-support): individua e ordina per priorità le verifiche, ma **non decide**. La determinazione resta in capo all'istruttore (cfr. §8 e giurisprudenza sull'algoritmo amministrativo).

### 1.2 In scope
- Raccolta continua di notizie e atti da fonti aperte e feed licenziati.
- Disambiguazione robusta dei soggetti (anti-omonimia).
- Classificazione del rischio secondo tassonomia **FATF** e calcolo di un **Adverse Media Index (AMI)** ancorato alla **materialità rispetto allo specifico intervento (CUP)**.
- Integrazione con i sistemi FSC/MASE (SIM, ReGiS, OpenCoesione, RNA, ARACHNE/PIAF via PDND).
- Human-in-the-loop (HITL) con escalation al controllo di I livello.

### 1.3 Out of scope
- **Decisioni automatiche** sull'erogazione dei fondi (vietato lo scoring puramente automatizzato — cfr. AI Act e principio di non esclusività della decisione algoritmica).
- **Profilazione** delle persone fisiche oltre il minimo necessario alla disambiguazione e alla materialità dell'alert (no arricchimenti non pertinenti allo scopo).
- Ricostruzione di analisi già coperte da ARACHNE/PIAF per il perimetro PNRR (si **consuma**, non si duplica).
- Fornitura dei dati sorgente: sono resi disponibili dall'ente e integrati via API/PDND o batch.

---

## 2. Architettura dell'applicazione

L'applicazione adotta un pattern **multi-agente orchestrato**, organizzato in tre layer.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — INGESTION                                                       │
│  News & atti · feed licenziati · registri pubblici (via connettori/PDND)  │
└───────────────┬──────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────┐
│  LAYER 2 — CORE MULTI-AGENT (orchestrazione LangGraph / Temporal)          │
│                                                                            │
│   [1] Entity        [2] Search &      [3] Classifi-   [4] AMI    [5] Conf. │
│       Resolution        Scraping          cazione FATF    Scoring    + HITL│
│         │                  │                  │            │          │    │
│         └──────────── Knowledge Graph condiviso (alias, UBO, relazioni) ───┘│
└───────────────┬──────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────┐
│  LAYER 3 — OUTPUT & GOVERNANCE                                             │
│  Alert + dossier per il I livello · Check-list & piste di controllo ·      │
│  Audit trail (GDPR / AI Act) · Feedback loop → ricalibrazione modelli      │
└──────────────────────────────────────────────────────────────────────────┘
```

**Principi guida**
- **Abstain by default**: auto-chiusura di un alert solo in presenza di prova; in dubbio si escala.
- **Difesa in profondità**: regole + ML + knowledge graph.
- **Full traceability**: ogni disposizione registra fonti, snippet, confidence, versione, decisione.
- **Continuous learning**: il feedback dell'analista ricalibra regole e modelli.
- **Human agency**: nessun effetto giuridico o significativo da output automatico; la sorveglianza umana è effettiva (art. 14 AI Act), non un timbro.

---

## 3. Componenti multi-agente

| # | Agente | Responsabilità | Tecniche chiave |
|---|--------|----------------|-----------------|
| 1 | **Entity Resolution** | Elimina gli omonimi prima del giudizio | Normalizzazione, transliterazione, matching su CF/P.IVA/CUP, NER (BERT/DSPy), similarità su embedding |
| 2 | **Search & Scraping** | Raccolta adattiva delle evidenze | Ricerca progressiva Broad → Targeted → Deep Dive → Alternative; early-termination sui soggetti "puliti" |
| 3 | **Classificazione FATF** | Categorizza gli articoli sul rischio | Dual-LLM (primario + secondario), Victim-Bystander Analysis, individuazione del ruolo processuale |
| 4 | **AMI Scoring** | Punteggio sintetico per soggetto | Severità × materialità (vs CUP/ruolo) × sentiment × credibilità fonte × freschezza × corroborazione |
| 5 | **Conflict Resolution + HITL** | Concilia i disaccordi ed escala | Framework multi-livello, validazione esterna, revisione umana obbligatoria sull'alto rischio |

---

## 4. Il modulo di Web Scraping in dettaglio

### 4.1 Pipeline di scraping

```
   Seed (soggetto disambiguato: nome, CF/P.IVA, alias, sede)
        │
        ▼
   [Query Builder] ── genera query mirate (reato, red flag, contesto territoriale)
        │
        ▼
   [Fetcher]  ── HTTP client + headless browser per pagine dinamiche
        │           · rispetto robots.txt / ToS / opt-out TDM · rate limiting · rotazione UA
        ▼
   [Extractor] ── boilerplate removal, estrazione testo/metadati (data, testata, autore)
        │
        ▼
   [Deduplica] ── hashing + similarità semantica (near-duplicate detection)
        │
        ▼
   [Language/Relevance filter] ── lingua, pertinenza, credibilità fonte
        │
        ▼
   [Provenance & timestamping] ── URL, fetch_ts, hash contenuto, marca temporale qualificata (eIDAS)
        │
        ▼
   Documento normalizzato → passa alla Classificazione FATF
```

### 4.2 Strategia di ricerca progressiva

| Modalità | Descrizione | Terminazione |
|----------|-------------|--------------|
| **Broad** | Ricerca ampia sul nominativo e varianti | Se nessun segnale → *early-termination* (soggetto pulito) |
| **Targeted** | Query mirate su reati/red flag e contesto | Prosegue se emergono match rilevanti |
| **Deep Dive** | Approfondimento fonti ad alta credibilità | Raccolta evidenze per l'AMI |
| **Alternative** | Fonti alternative / multilingua | Solo se le precedenti sono inconcludenti |

### 4.3 Strategia sulle fonti: *build-vs-buy* (compliant by design)

> **Principio operativo.** Lo scraping "puro" delle testate generaliste è la componente **più fragile e più esposta** (paywall, ToS che vietano il *text-and-data mining*, `robots.txt`, *layout drift*, copertura non strutturata) e il canale con la **minor resa** in termini di evidenza qualificata. La progettazione adotta quindi una gerarchia esplicita delle fonti.

**Gerarchia delle fonti (dalla più alla meno preferita)**

1. **Feed licenziati AML/KYC** come *spina dorsale* dell'adverse media, dove disponibili e acquistati: Dow Jones Risk & Compliance / Factiva, LexisNexis WorldCompliance, Moody's (Orbis + Grid). Coprono in modo strutturato PEP, sanzioni, watchlist e *adverse media* con provenienza e licenza d'uso.
2. **API e open data istituzionali** (basso rischio giuridico, alta affidabilità): OpenCoesione/OpenCUP, RNA, BDNCP-ANAC (via PDND), InfoCamere/Telemaco, Gazzette e Bollettini ufficiali.
3. **Scraping mirato di fonti pubbliche/istituzionali ad alto valore e basso rischio**: albo pretorio, BUR regionali, comunicati di Procure / Guardia di Finanza / forze dell'ordine, delibere e provvedimenti ANAC, atti giudiziari pubblicati.
4. **Scraping di testate**: **solo** ove consentito da licenza o da ToS/`robots.txt` e nel rispetto dell'**opt-out TDM** (art. 4 Dir. UE 2019/790; artt. 70-*ter*/70-*quater* L. 633/1941). Nessun aggiramento di paywall o DRM.

**Buone pratiche trasversali**
- **Rispetto di `robots.txt`, Termini di Servizio e opt-out TDM**; preferenza per API ufficiali e feed licenziati.
- **Rate limiting** e back-off esponenziale; nessun aggiramento di paywall o DRM.
- **Rotazione di User-Agent e sessioni** per robustezza, non per elusione (User-Agent identificabile e, dove opportuno, pagina di contatto).
- **Caching** dei contenuti già visti e **change detection** per il re-screening.
- **Provenienza tracciata**: URL, timestamp di fetch, hash del contenuto e **marca temporale qualificata (eIDAS)** per il valore probatorio dell'evidenza.
- **Politeness policy** centralizzata e configurabile per dominio (registro fonti con crawl-delay, quote, credibilità e livello di rischio legale).

### 4.4 Anti-fragilità
- Coda di lavori con retry idempotenti (Temporal/Celery).
- Circuit breaker sui domini non raggiungibili.
- Snapshot dei contenuti (WARC/HTML) per riproducibilità delle evidenze.
- Test di regressione sugli estrattori e alert su *drift* di layout.

---

## 5. Fonti dati e integrazioni

| Sistema / fonte | Cosa fornisce | Accesso |
|-----------------|---------------|---------|
| **Feed licenziati AML/KYC** | Adverse media, PEP, sanzioni, watchlist (strutturato) | Licenza commerciale (Dow Jones, LexisNexis, Moody's Grid) |
| **News & atti · COLAF** | Stampa, atti giudiziari, comunicati | Feed licenziati / scraping conforme |
| **ReGiS** (PNRR/PNC MASE) | Procedure, beneficiari, milestone; collegato a ORBIS/ARACHNE/PIAF | Amministrazione titolare |
| **OpenCoesione / OpenCUP** | Progetti FSC, CUP, stato attuazione | Dump pubblici / API |
| **RNA — Registro Aiuti** | Aiuti concessi, cumuli e incompatibilità | Fonte pubblica |
| **ARACHNE / PIAF-IT** | Scoring antifrode e interoperabilità (perimetro PNRR) | Via ReGiS (consumo) |
| **BDNCP — ANAC** | Contratti, subappalti, CIG per P.IVA | Via **PDND** (e-service), previa autorizzazione |
| **InfoCamere / Telemaco** | Visure, catena partecipativa, titolare effettivo | Accordo/servizio |
| **SISTER / Catasto** | Patrimonio immobiliare, coerenza asset | Servizio |
| **BDU / SNM** (IGRUE-RGS) | Banca Dati Unitaria FSC, monitoraggio | Protocollo Unico di Colloquio |

> **Punto di integrazione**: il **CUP** lega il dato finanziario (chi finanzia, quanto, milestone) al soggetto; la riconciliazione a livello di CUP è il principale lavoro di data engineering ed è **anche il pilastro della materialità** dell'alert (vedi §7.3).

### 5.1 Registro fonti e credibilità
Ogni fonte è censita in un **registro** con: tipo (feed/API/scraping), **livello di credibilità** (alta/media/bassa, con criteri documentati — es. fonte primaria istituzionale vs aggregatore), **livello di rischio legale** (licenza, ToS, opt-out TDM), politeness policy (crawl-delay, quote) e note di conservazione. Il livello di credibilità alimenta l'AMI (§7.3) e la credibilità dichiarata in ogni `evidence` deriva da questo registro, non da stima ad-hoc.

---

## 6. Stack tecnologico

| Area | Tecnologie proposte |
|------|---------------------|
| **Orchestrazione agenti** | LangGraph / Temporal |
| **Scraping** | Playwright (pagine dinamiche), HTTPX/requests, Scrapy (crawling strutturato) |
| **Estrazione contenuti** | trafilatura / readability, BeautifulSoup, lxml |
| **NLP / NER** | spaCy, transformer BERT, DSPy per moduli modulari |
| **LLM** | Modelli via API/on-prem per classificazione FATF (dual-LLM) |
| **Vector DB / RAG** | FAISS / pgvector per retrieval e near-duplicate detection |
| **Knowledge graph** | Neo4j / grafo su Postgres per alias, UBO, relazioni |
| **Storage** | PostgreSQL (dati strutturati), object store per snapshot WARC/HTML |
| **Coda & scheduling** | Temporal / Celery + Redis |
| **API & UI** | FastAPI (backend), interfaccia investigativa per HITL (accessibile — L. 4/2004) |
| **Explainability** | SHAP, tracciamento delle evidenze per ogni score |
| **Piattaforma analitica** | SAS Viya (Agentic AI, Model Management) per integrazione nei flussi antifrode |
| **Osservabilità** | OpenTelemetry, logging strutturato, audit log immutabile |
| **Sicurezza / residenza dati** | Cifratura at-rest/in-transit, segregazione accessi (RBAC/ABAC), cloud qualificato ACN, dati in UE |

---

## 7. Modello dati e output

### 7.1 Entità principali
- **Subject** — soggetto sotto screening (beneficiario / attuatore / impresa esecutrice / UBO).
- **Evidence** — documento/notizia raccolto (URL, testata, data, snippet, hash, provenance, marca temporale).
- **Classification** — categoria FATF, ruolo processuale (indagato/imputato/condannato · autore/vittima/menzionato), confidence.
- **AMI Score** — punteggio sintetico + fattori esplicativi.
- **Alert** — esito con stato workflow (aperto / auto-chiuso / escalato / disposto).

### 7.2 Ruolo processuale (obbligatorio)
Ogni evidenza penalmente rilevante è qualificata per **fase e ruolo**: *notizia di reato / indagine preliminare / rinvio a giudizio / condanna non definitiva / condanna definitiva / archiviazione-proscioglimento*. La distinzione è vincolante per la tutela della **presunzione di innocenza** (art. 27 Cost.) e governa retention e decadenza (§8.4): un'archiviazione o un proscioglimento nota deve **abbattere o azzerare** il contributo dell'evidenza.

### 7.3 AMI — fattori
```
AMI = f( severità_reato,
         materialità_vs_intervento,     ← nesso con CUP/CIG e ruolo del soggetto
         sentiment,
         credibilità_fonte,             ← dal registro fonti (§5.1)
         freschezza / decadimento,      ← le evidenze datate/archiviate decadono
         corroborazione_multi-fonte,
         ruolo_processuale )            ← gate: perpetratore ≠ vittima/menzionato
```
La **materialità** è ciò che rende l'alert azionabile e difendibile: non "il soggetto ha bad news", ma "questa bad news è **rilevante per *questo* intervento FSC**", tenuto conto del ruolo (esecutore vs beneficiario vs UBO) e dell'importo/fase del CUP.

### 7.4 Esempio di output alert (JSON)

```json
{
  "subject": {
    "denominazione": "ACME Costruzioni S.r.l.",
    "cf_piva": "01234567890",
    "cup": ["E51B21000000001"],
    "ruolo": "impresa esecutrice"
  },
  "ami_score": 82,
  "risk_level": "ALTO",
  "fatf_categories": ["Fraud & Financial Crime", "Corruption & Bribery"],
  "drivers": [
    "Beneficiario neocostituito vs data domanda",
    "CUP su più programmi (possibile doppio finanziamento)",
    "Bad news su UBO: indagine per turbativa d'asta"
  ],
  "evidence": [
    {
      "url": "https://esempio-testata.it/articolo",
      "testata": "Quotidiano X",
      "data": "2026-07-21",
      "snippet": "…sequestro preventivo nei confronti di…",
      "fonte_credibilita": "alta",
      "fetch_ts": "2026-09-02T08:14:00Z",
      "hash": "sha256:…",
      "timestamp_qualificato": "eidas-tsa:…",
      "ruolo_processuale": "indagine_preliminare"
    }
  ],
  "role_analysis": "perpetratore (non vittima/menzionato)",
  "materialita": {
    "cup_collegato": "E51B21000000001",
    "nesso": "il soggetto è esecutore dell'intervento; il reato ipotizzato incide sulla procedura di affidamento",
    "livello": "alta"
  },
  "disposition": "ESCALATION_I_LIVELLO",
  "audit": {
    "modello_versione": "fatf-clf-1.4",
    "entity_resolution": { "match": "deterministico_CF", "confidence": 0.99 },
    "operatore": null,
    "presunzione_innocenza_flag": true
  }
}
```

---

## 8. Governance, conformità e sicurezza

> **Nota (revisione v1.1).** Questa sezione è il baricentro di rischio del progetto ed è stata rafforzata sui punti più esposti: base giuridica per i **dati giudiziari (art. 10 GDPR)**, **FRIA (art. 27 AI Act)**, sorveglianza umana effettiva, ciclo di vita del dato e conciliazione fra audit immutabile e diritto alla cancellazione.

### 8.1 Basi giuridiche del trattamento
- **Dati "comuni"** (PA): interesse pubblico / esercizio di pubblici poteri — **art. 6(1)(e) GDPR + art. 2-*ter* Codice Privacy** — non il consenso.
- **Dati relativi a condanne penali e reati (art. 10 GDPR)**: l'adverse media screening è, nella sostanza, trattamento di dati giudiziari. L'art. 6(1)(e) **non è sufficiente**: l'art. 10 GDPR e l'**art. 2-*octies* del Codice Privacy** richiedono che il trattamento sia **autorizzato da una norma di legge o, nei casi previsti, di regolamento** che individui finalità, garanzie e misure appropriate. → **Azione richiesta**: individuare/istituire con il legale la **base normativa specifica** (o l'atto regolamentare) che abiliti il trattamento dei dati giudiziari nel perimetro del controllo FSC, prima di trattare tali dati in produzione. È il primo rilievo che solleverebbe il DPO.
- **Dati particolari (art. 9 GDPR)**: evitare la raccolta di categorie particolari (salute, opinioni, ecc.); se emergono incidentalmente da una notizia, vanno minimizzate e non usate come driver.

### 8.2 AI Act (Reg. UE 2024/1689)
- Il sistema è classificato **prudenzialmente ad alto rischio** (ausilio a decisioni che incidono su accesso/mantenimento di risorse pubbliche). L'esatto inquadramento in **Allegato III** va confermato in sede di valutazione.
- Obblighi conseguenti: **DPIA (art. 35 GDPR) + FRIA — Valutazione d'impatto sui diritti fondamentali (art. 27 AI Act)**, obbligatoria per i deployer **organismi pubblici**; **governance dei dati** (art. 10 AI Act), **trasparenza** (art. 13), **sorveglianza umana** (art. 14), **registrazione/log** (art. 12), **accuratezza e robustezza** (art. 15).
- **Esclusione dello scoring puramente automatizzato** e assenza di effetti giuridici da output automatico (coerente con art. 22 GDPR).

### 8.3 Principio dell'algoritmo amministrativo (giurisprudenza IT)
Coerentemente con la giurisprudenza del Consiglio di Stato (tra le altre, 2270/2019, 8472/2019, 881/2020), la decisione amministrativa che si avvale di algoritmi rispetta:
- **Conoscibilità e comprensibilità** (spiegabilità dell'esito);
- **Non esclusività** della decisione algoritmica (deve esservi un funzionario umano responsabile);
- **Non discriminazione** algoritmica (controllo su bias e correttezza dei dati).
Il design HITL + explainability + audit trail è la traduzione operativa di questi principi.

### 8.4 Ciclo di vita del dato e retention
| Categoria | Esempio | Trattamento retention |
|-----------|---------|-----------------------|
| Esito "pulito" (early-termination) | Nessun match rilevante | Si conserva l'esito/log della verifica, **non** il contenuto raccolto; cancellazione a breve |
| Evidenza confermata e materiale (alert disposto) | Sequestro collegato al CUP | Conservata per la durata del procedimento di controllo + termini di conservazione atti FSC, poi cancellazione/archiviazione |
| Indagine poi archiviata / proscioglimento | Indagato poi archiviato | **Oblio/decadenza** appena nota l'archiviazione; l'evidenza è marcata "superata" e non pesa sull'AMI |
| Snapshot WARC/HTML probatorio | Pagina catturata | Conservato con l'evidenza collegata; pseudonimizzato quando non più necessario |
| Audit trail (decisioni, versioni) | Log immutabile | Lungo termine per accountability/rendicontazione UE, con minimizzazione dei dati personali |

### 8.5 Audit immutabile vs diritto alla cancellazione
L'audit trail è immutabile **per le decisioni e i metadati**, non per i contenuti personali. La conciliazione con gli artt. 16-17 GDPR (rettifica/cancellazione) avviene tenendo l'audit su **identificatori pseudonimizzati e hash**, e applicando la cancellazione del contenuto sottostante tramite *crypto-shredding* (distruzione della chiave) o *tombstoning*, preservando la tracciabilità della decisione senza trattenere il dato personale non più necessario.

### 8.6 Equità e non discriminazione
Monitoraggio del **bias**: l'adverse media può sistematicamente sovra-segnalare nomi esteri, translitterazioni e alias. Si misurano tassi di falsi positivi per categorie a rischio e si documentano le mitigazioni (Entity Resolution deterministica, soglie calibrate, revisione umana).

### 8.7 Altri presidi
- **Screening, non prova**: gli alert sono priorità di verifica qualificate; la decisione resta all'istruttore.
- **Minimizzazione dei dati** e retention definita; pseudonimizzazione dove possibile.
- **Sicurezza**: segregazione degli accessi (RBAC/ABAC), cifratura at-rest/in-transit, audit log immutabile, misure minime AgID, cloud qualificato ACN, **dati in UE**.
- **Disambiguazione obbligatoria**: nessun giudizio senza Entity Resolution superata (tutela anti-omonimia).
- **Sinergia, non duplicazione**: complementare ad ARACHNE/PIAF; aggiunge il segnale "notizie negative" oggi non coperto dalle piattaforme.

---

## 9. Piano di sviluppo

Il piano segue un **roll-out incrementale** allineato al pilota MASE, così da produrre valore già dalle prime settimane. Le richieste di accesso alle fonti esterne — **e la definizione della base giuridica ex art. 10 GDPR** — partono il **primo giorno** (percorso critico).

### 9.1 Fasi e milestone

| Fase | Orizzonte | Contenuti | Esito atteso |
|------|-----------|-----------|--------------|
| **Avvio** | Settimana 1 | Onboarding PDND · e-service ANAC · accessi BDU-FSC/InfoCamere · avvio **DPIA + FRIA** · **base giuridica art. 10** con il legale · setup ambiente e CI/CD | Accessi avviati, guardrail impostati |
| **Rilascio 1** | Sett. 6-10 | **Entity Resolution** beneficiari/attuatori · **Adverse Media MVP** (news + registri pubblici) · doppio finanziamento deterministico via CUP (ReGiS + OpenCoesione) | Primi alert in produzione |
| **Rilascio 2** | Mesi 3-4 | **Search/Scraping a regime** + **AMI scoring** · consumo ARACHNE/PIAF · imprese esecutrici via PDND-ANAC | Copertura estesa, scoring completo |
| **Rilascio 3** | Mesi 5-7 | OCR/NER operatori tecnici da PDF · **network analysis a grafo** (HITL) · piena operatività starting pack | Sistema completo e conforme |

### 9.2 Backlog per fase (epiche → attività)

**Avvio (Settimana 1)**
- [ ] Setup repository, ambienti (dev/test/prod), pipeline CI/CD.
- [ ] Avvio pratiche di accesso: onboarding PDND, e-service ANAC, InfoCamere, BDU-FSC.
- [ ] Kickoff **DPIA + FRIA** con il legale (compliance by design) e **individuazione della base giuridica ex art. 10 GDPR / art. 2-*octies***.
- [ ] Definizione data contract e riconciliazione a livello di **CUP**.
- [ ] Redazione del **registro fonti** iniziale (credibilità + rischio legale + politeness).

**Rilascio 1 (Sett. 6-10)**
- [ ] Modulo **Entity Resolution** (normalizzazione, matching deterministico CF/P.IVA/CUP, NER).
- [ ] **Scraper MVP** conforme (robots.txt, opt-out TDM, rate limiting, provenance, marca temporale) su fonti pubbliche e news licenziate.
- [ ] Estrazione contenuti + deduplica + filtro pertinenza/lingua.
- [ ] Regola deterministica **doppio finanziamento** via CUP (ReGiS + OpenCoesione).
- [ ] UI investigativa base per HITL + audit log.

**Rilascio 2 (Mesi 3-4)**
- [ ] Search adattiva completa (Broad→Targeted→Deep Dive→Alternative) + early-termination.
- [ ] **Classificazione FATF dual-LLM** + Victim-Bystander Analysis + ruolo processuale.
- [ ] **AMI scoring** con fattori esplicativi (SHAP), inclusa **materialità vs CUP** e decadimento.
- [ ] Connettore **PDND-ANAC** (BDNCP) per imprese esecutrici.
- [ ] Consumo segnali **ARACHNE/PIAF** per il perimetro PNRR.

**Rilascio 3 (Mesi 5-7)**
- [ ] Pipeline **OCR/NER** per operatori tecnici da PDF (determine, verbali).
- [ ] **Network analysis a grafo** (Neo4j) con guardrail GDPR/AI Act e HITL.
- [ ] Ricalibrazione modelli su feedback, tuning soglie, **monitoraggio bias**, hardening.
- [ ] Documentazione, formazione utenti, passaggio in esercizio.

### 9.3 Gantt sintetico

```
Settimane →     1   2   4   6   8  10   12   16   20   24   28
Avvio/Accessi  ████████████████████████████░░ (percorso critico, 2-4 mesi)
Base giur. art.10 ████░ (blocca il trattamento dati giudiziari)
Entity Res.        ██████░
Scraper MVP          ██████░
Doppio finanz.          ████░
Search a regime               ████████░
FATF + AMI                      ██████████░
PDND-ANAC                          ████████░ (dipende da accesso)
OCR/NER                                     ██████████░
Network graph                                   ██████████░
Hardening/esercizio                                    ████████
```

### 9.4 Team e capacità
- **3-5 persone**: 1 tech lead, 1-2 data/ML engineer, 1 backend/scraping engineer, 1 esperto compliance (part-time con il legale).
- Due flussi di lavoro in parallelo (SIM-native vs dipendenza esterna) per far scorrere il tempo amministrativo in sovrapposizione allo sviluppo.

---

## 10. Rischi e mitigazioni

| Rischio | Impatto | Mitigazione |
|---------|---------|-------------|
| **Assenza di base giuridica ex art. 10 GDPR** per i dati giudiziari | Alto — blocca il trattamento | Individuazione/istituzione della norma abilitante il giorno 1; fino ad allora, nessun trattamento di dati giudiziari in produzione |
| **Tempi di accesso alle fonti esterne** (PDND, ANAC, InfoCamere, BDU) | Alto — percorso critico | Avvio pratiche il giorno 1, monitoraggio come rischio di programma |
| **Falsi positivi da omonimia** | Alto (legale/reputazionale) | Entity Resolution obbligatoria prima del giudizio |
| **Bias / discriminazione** (nomi esteri, alias) | Alto (giuridico/reputazionale) | Monitoraggio FP per categoria, soglie calibrate, HITL, documentazione |
| **Blocco/anti-bot e vincoli ToS/licenza delle fonti** | Medio | Preferenza per API/feed licenziati, opt-out TDM, politeness policy, back-off |
| **Cambi di layout delle pagine** | Medio | Estrattori robusti (readability), test di regressione, alert su drift |
| **Conformità AI Act/GDPR** | Alto | DPIA/FRIA anticipate, HITL, no scoring automatico, audit trail |
| **Valore probatorio dell'evidenza** contestabile | Medio | Snapshot WARC + hash + **marca temporale qualificata (eIDAS)**, provenienza |
| **Qualità del dato** | Medio | Gateway di data cleaning, validazione, riconciliazione CUP |
| **Sovrapposizione con ARACHNE/PIAF** | Basso | Consumo dei segnali esistenti, focus sul valore aggiunto "bad news" |

---

## 11. Criteri di accettazione (Definition of Done)

- [ ] Ogni alert è **spiegabile** e ancorato alle evidenze (URL, snippet, hash, timestamp qualificato).
- [ ] Nessun alert prodotto senza **Entity Resolution** superata.
- [ ] Esiste una **base giuridica documentata** per il trattamento dei dati ex art. 10 GDPR prima del go-live sui dati giudiziari.
- [ ] **DPIA + FRIA** completate e approvate prima del passaggio in esercizio.
- [ ] Ogni evidenza penalmente rilevante riporta il **ruolo processuale**; archiviazioni/proscioglimenti abbattono l'AMI.
- [ ] **Audit trail** completo e immutabile per ogni disposizione, conciliato con i diritti di rettifica/cancellazione.
- [ ] Scraping conforme a robots.txt/ToS/opt-out TDM, con rate limiting e provenance.
- [ ] Metriche di qualità: precision/recall sul set di validazione entro le soglie concordate; **metriche di bias** monitorate.
- [ ] **HITL** operativo: gli alert ad alto rischio richiedono revisione umana con potere effettivo di override.
- [ ] Nessuna decisione automatica sull'erogazione (conformità AI Act e principio di non esclusività).
- [ ] Documentazione tecnica, runbook operativo e materiale di formazione consegnati.

---

## Appendice A — Changelog v1.0 → v1.1

Revisione tecnica esperta (adverse media / compliance PA). Modifiche materiali:

1. **Base giuridica art. 10 GDPR / art. 2-*octies*** (dati giudiziari) resa esplicita come pre-condizione bloccante e inserita in §8.1, §9 (Avvio, giorno 1), §10 e §11. Nella v1.0 la compliance citava solo l'art. 6(1)(e) + art. 2-*ter*, insufficienti per i dati giudiziari.
2. **Strategia *build-vs-buy* sulle fonti** (§4.3) con gerarchia esplicita: feed licenziati come spina dorsale, scraping ristretto alle fonti pubbliche/istituzionali ad alto valore e basso rischio; **opt-out TDM** (Dir. UE 2019/790, artt. 70-*ter*/70-*quater* L. 633/1941).
3. **Materialità rispetto al CUP** integrata nell'AMI (§7.3, §5) e nell'output JSON: l'alert è ancorato al nesso con lo specifico intervento e al ruolo del soggetto.
4. **Ruolo processuale e presunzione d'innocenza** (§7.2): distinzione indagato/imputato/condannato/archiviato, con decadenza dell'AMI su archiviazioni/proscioglimenti.
5. **FRIA (art. 27 AI Act)** e **sorveglianza umana (art. 14)** esplicitate; chiarito DPIA (art. 35 GDPR) + FRIA in luogo del generico "AIA" (§8.2).
6. **Principio dell'algoritmo amministrativo** (Consiglio di Stato) come fondamento del design HITL/explainability (§8.3).
7. **Ciclo di vita del dato / retention** (§8.4) e **conciliazione audit immutabile vs diritto alla cancellazione** via crypto-shredding/tombstoning (§8.5).
8. **Monitoraggio del bias** (§8.6, §10, §11).
9. **Valore probatorio**: marca temporale qualificata eIDAS su ogni evidenza (§4.1, §4.3, §7, §10).
10. **Registro fonti** con credibilità e rischio legale (§5.1), a monte del campo `fonte_credibilita`.
11. **Sicurezza/residenza**: misure minime AgID, cloud qualificato ACN, dati in UE (§6, §8.7).

## Appendice B — Riferimenti normativi

- **GDPR** (Reg. UE 2016/679): art. 6(1)(e), art. 9, **art. 10**, art. 12-17, art. 22, art. 35.
- **Codice Privacy** (D.lgs. 196/2003 e s.m.i.): art. 2-*ter*, **art. 2-*octies***.
- **AI Act** (Reg. UE 2024/1689): Allegato III, art. 10 (governance dati), art. 12-15, art. 26, **art. 27 (FRIA)**.
- **Direttiva Copyright DSM** (UE 2019/790), artt. 3-4 (TDM); recepimento IT: artt. 70-*ter*/70-*quater* L. 633/1941 (D.lgs. 177/2021).
- **eIDAS** (Reg. UE 910/2014): validazione temporale qualificata.
- **Costituzione**: art. 27 (presunzione di innocenza).
- **Giurisprudenza algoritmo amministrativo**: Cons. Stato 2270/2019, 8472/2019, 881/2020.
- **Accessibilità**: L. 4/2004; linee guida AgID.
- **Sicurezza PA**: misure minime AgID; qualificazione cloud ACN.

---

*Documento tecnico-funzionale — uso interno — allineato all'architettura dell'agente di Adverse Media Screening per i beneficiari FSC (pilota MASE). I riferimenti normativi hanno finalità di indirizzo progettuale e vanno validati con il legale/DPO in sede di DPIA e FRIA.*
