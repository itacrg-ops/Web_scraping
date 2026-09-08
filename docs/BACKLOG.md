# Backlog — Adverse Media Screening (pilota MASE/FSC)

Aggiornato: 2026-09-08 · Ordine dei componenti: `services/*`, `admin-console/`.

Elenco prioritizzato delle evoluzioni. La pipeline di base è operativa e
collaudata end-to-end (registro Soggetti, web search multi-sintassi con
anti-omonimia a due livelli, Entity Resolution, fetch+mention, FATF, AMI pesato,
SVI mock, alert con evidenze). Questo documento traccia i passi successivi.

## Legenda

- **Priorità** — `P0` bloccante (compliance / pilota non avviabile senza);
  `P1` operativo essenziale; `P2` qualità/copertura/accuratezza.
- **Effort** — `S` (≤ ~2 gg), `M` (~1 settimana), `L` (> 1 settimana), stime
  indicative da raffinare in analisi.

## Quadro sinottico

| ID | Titolo | Priorità | Effort | Componenti principali |
|----|--------|:--------:|:------:|-----------------------|
| B1 | Redazione PII prima dell'LLM | **P0** | M | `llm-gateway`, `worker-scraping` |
| B2 | Payload SVI reali | P1 | M | `svi-publisher` |
| B3 | Observability (metriche/log/tracing) | P1 | M | tutti i servizi, `docker-compose` |
| B4 | Rate limiter distribuito su Redis | P1 | S–M | `search-gateway`, `redis` |
| B5 | Scoring AMI completo | P2 | M | `worker-scraping` |
| B6 | Headless browser (fonti JS) | P2 | M | `worker-scraping` |
| B7 | NER / Embedding per l'anti-omonimia | P2 | L | `entity-resolution`, `worker-scraping` |
| B8 | Multi-provider fan-out ricerca | P2 | M | `search-gateway`, `docker-compose` |
| B9 | Feed di rischio strutturato (Crime&tech) | P2 | M | `risk-gateway` (nuovo), `worker-scraping` |

**Sequenza adottata (pilota): B1 → B6 → B7 → B8** — compatibilità verificata sul
codice. B1 parte in versione **MVP regex** (indipendente); dopo B7 va rifinita con
NER (vedi **B1.1**). B6 precede B7 così il NER lavora su testo più ricco
(JS-rendered); B8 per ultimo, quando gli stadi a monte (PII, estrazione,
disambiguazione) sono già solidi e il volume di articoli cresce.

_Sequenza alternativa a priorità pura (compliance+operatività prima):_
B1 → (B2, B3, B4 in parallelo) → B8 → B5 → B6 → B7.

---

## B1 — Redazione PII prima dell'invio all'LLM · P0

**Stato: ✅ FATTO (con B1.1).** Modulo `services/llm-gateway/app/pii.py` + hook in
`foundry.classify` (chokepoint egress), toggle `PII_REDACTION`, audit nel campo
`pii_redaction`, test `tests/test_pii.py`. **B1.1 FATTA**: i **nomi di persona**
sono pseudonimizzati via NER — soggetto → `[SOGGETTO]`, terzi → `[PERSONA]` (flag
`REDACT_PERSON_NAMES`); ad Azure non arriva alcun nome reale e il marcatore aiuta
la Victim-Bystander.

**Perché.** È la voce più urgente per la compliance **GDPR / AI Act**. Oggi il
testo degli articoli — che contiene dati personali di **terzi** (non solo il
soggetto) — viene inviato ad Azure AI Foundry per la classificazione FATF
**senza mascheramento**. Minimizzazione (art. 5 GDPR) e trasparenza/DPIA (AI Act)
impongono di ridurre le PII trasmesse a un processore esterno.

**Scope.** Modulo di redazione/pseudonimizzazione che, **prima** della
classificazione, sostituisce con placeholder le PII non necessarie (nominativi di
terzi diversi dal soggetto, indirizzi, CF/P.IVA, email, telefoni, IBAN),
conservando il soggetto-target e il contesto utile alla classificazione.

**Componenti.** Chokepoint unico verso Azure: `services/llm-gateway/app/foundry.py`
(`_classify_one`, unico punto in cui il testo lascia il perimetro). In alternativa
nel worker, tra la costruzione di `combined` e `classify_fatf`
(`services/worker-scraping/workflows.py`) — la verifica di menzione avviene **prima**,
quindi la redazione non rompe il match del soggetto. Nuovo modulo `pii_redaction`.

**B1.1 (✅ FATTA, dopo B7).** Redazione dei **nomi** via NER (`/v1/ner`): il nome
del soggetto (persona) → `[SOGGETTO]` anche senza NER (è noto), i terzi → `[PERSONA]`
quando la NER è disponibile. Il regex-MVP copre CF/P.IVA, email, telefoni, IBAN;
i nomi arbitrari li copre la NER.

**Definition of Done.**
- il payload verso Azure non contiene PII non-soggetto (test di verifica);
- toggle di configurazione (default: redazione attiva in ambienti non-mock);
- log di **audit** di cosa è stato redatto (categoria, conteggio — non il valore);
- nota DPIA aggiornata.

## B2 — Payload SVI reali · P1

**Stato: ✅ FATTO (ramo live pronto; attivazione a Viya disponibile).** Publisher
reale in `services/svi-publisher`: **mapping** alert→SVI (documento Data Hub +
alert) in `app/mapping.py` (puro, testato), **auth** OAuth2 SASLogon / broker in
`app/auth.py`, **retry con backoff** e **idempotenza** (business key =
`screening_id`) in `app/svi_client.py`. Payload arricchito con **evidenze +
motivazione** (il worker le costruisce prima della pubblicazione). Modello dati
(tipo oggetto/alert/coda/attributo esterno) **configurabile** da `.env`
(deployment-specific). `SVI_MODE=mock` invariato in locale. Test 7/7. Dettaglio e
attivazione in [`SVI_INTEGRATION`](SVI_INTEGRATION.md).

**Perché.** Sblocca l'operatività investigativa: in `SVI_MODE=mock` gli alert
restano nella console React e **l'istruttore non li vede in SVI**.

**Scope.** Publisher reale: mapping `AMI / categorie FATF / evidenze / motivazione`
→ schema SVI; autenticazione all'ambiente; gestione errori con retry;
**idempotenza** (nessun alert duplicato su ripubblicazione).

**Componenti.** `services/svi-publisher`; `services/worker-scraping` (payload SVI
con evidenze/screening_id).

**Dipendenze (per l'attivazione live).** Un ambiente **Viya/SVI** con il **data
model** configurato (tipi oggetto/alert/coda) + credenziali OAuth. Oggi l'egress
verso Viya è comunque bloccato dal proxy dell'ambiente; il ramo live è
implementato e testato nelle parti pure, non ancora esercitato su Viya reale.

**Definition of Done.** Un alert prodotto dalla pipeline compare in SVI con
evidenze e motivazione; retry e idempotenza verificati; mock invariato in locale.

## B3 — Observability · P1

**Perché.** Senza metriche il sistema è una **scatola nera** operativa: non si
misura carico, latenza, tasso di 429, esiti del gate, distribuzione AMI.

**Scope.**
- **Metriche** (Prometheus): richieste/latenze per servizio, esiti Entity
  Resolution (`resolved/ambiguous/needs_review/…`), esiti ricerca per provider e
  429, distribuzione AMI/risk level, articoli con/senza menzione;
- **Log strutturati** con `correlation-id` propagato lungo il workflow;
- **Health/readiness** uniformi; dashboard base (Grafana);
- (opzionale) **tracing** OpenTelemetry per la catena ER→search→fetch→classify.

**Componenti.** Middleware comune ai servizi (`api`, `search-gateway`,
`entity-resolution`, `worker-scraping`, `llm-gateway`, `svi-publisher`);
`docker-compose.dev.yml` (Prometheus + Grafana).

**Definition of Done.** `/metrics` per servizio; dashboard con i KPI chiave;
correlation-id visibile end-to-end su un caso di esempio.

## B4 — Rate limiter distribuito su Redis · P1

**Perché.** Critico per la scalabilità. Il throttle attuale di GDELT/Brave è
**in-process** (`asyncio.Lock` + variabili globali in `providers.py`): con più
worker/repliche ogni processo ha il proprio contatore, quindi i limiti upstream
(GDELT ~1 req/5s, Brave free ~1 req/s) vengono **superati** → 429.

**Scope.** Rate limiter **distribuito** (token bucket) su Redis, condiviso tra le
repliche, per-provider; sostituisce `_throttle_gdelt` / `_throttle_brave`
mantenendo l'interfaccia.

**Componenti.** `services/search-gateway/app/providers.py`; `redis` (già nello
stack).

**Definition of Done.** Con N repliche del gateway il rate verso ciascun provider
resta sotto soglia (test di concorrenza); nessuna regressione sul singolo worker.

## B5 — Scoring AMI completo · P2

**Perché.** Migliora la pertinenza. L'AMI attuale =
`base(severità FATF) × credibilità × corroborazione` con cap vittima/bystander.
Mancano materialità sul CUP, freschezza e sentiment.

**Scope.**
- **Materialità CUP** — peso in base a ruolo/esposizione del soggetto
  sull'intervento (RUP, esecutore, beneficiario) e pertinenza dell'evidenza al CUP;
- **Freschezza** — decadimento temporale (le notizie recenti pesano di più);
- **Sentiment** — polarità negativa dell'articolo come modulatore.

**Componenti.** `services/worker-scraping/app` (`compute_ami`); il registro
fornisce già ruolo/CUP; il sentiment può appoggiarsi all'`llm-gateway`.

**Definition of Done.** L'AMI incorpora materialità + freschezza (+ sentiment se
abilitato) con **pesi configurabili** e spiegazione nei driver; test su casi noti.

## B6 — Headless browser per fonti JS-rendered · P2

**Stato: ✅ FATTO.** Modulo `render.py` (Playwright/Chromium) + activity
`render_source` instradata nella stessa pipeline snapshot/hash/WARC; il workflow
fa il fallback quando l'estrazione HTTP è < ~400 caratteri e tiene la versione con
più testo. Playwright + Chromium aggiunti all'immagine `worker-scraping`; toggle
`HEADLESS_FALLBACK`. Driver dedicato nell'alert.

**Perché.** Aumenta la copertura: il fetch attuale è HTTP semplice, mentre
~30–40% dei siti moderni rende i contenuti in JavaScript e oggi tornano quasi
vuoti. Un browser headless (**Playwright**) recupera il contenuto renderizzato.

**Scope.** Fallback a Playwright quando l'estrazione semplice trova poco contenuto
(euristica su lunghezza/qualità); pool e timeout; rispetto di robots/UA; controllo
di costo e latenza (usato solo quando serve). **Richiede** l'aggiunta di Playwright
+ browser all'immagine `worker-scraping` (oggi: `temporalio, httpx, trafilatura,
boto3, warcio`; nessun browser incluso), con impatto su dimensione immagine e avvio.

**Componenti.** `services/worker-scraping` (`fetch_source` / `extract_content`).

**Definition of Done.** Un set di URL JS-rendered noti passa da "vuoto" a
"contenuto estratto"; fallback attivato solo quando necessario; limiti di risorsa.

## B7 — NER / Embedding per l'anti-omonimia · P2

**Stato: ✅ parte 1 FATTA.** Disambiguazione per **CUP** dell'intervento nel gate
(`probabilistico_nome_CUP`: riduce gli `ambiguous` sugli omonimi) + **embedding**
opt-in per le varianti di nome (llm-gateway `/v1/embed` + blend in `resolver.py`,
fallback a stringa). Test `tests/test_resolver_b7.py`.

Aggiunti (persona fisica): **coerenza CF ↔ dati anagrafici** (decode del CF; gate
`incoerenza_CF_dati_anagrafici` + avviso live in console, `/cf-check`,
`tests/test_codice_fiscale.py`), **luogo di nascita** (campo/colonna CSV +
disambiguatore, migrazione DB 0004), **estrazione anagrafica dagli articoli** (età/
anno/luogo → corroborazione o "possibile OMONIMO", `worker/anagraphics.py`).

**Parte 2: ✅ FATTA.** NER italiana (spaCy `it_core_news_sm`) nel llm-gateway
(`/v1/ner`); il worker la usa per corroborare (soggetto = persona, azienda =
organizzazione), con toggle `NER_CORROBORATION` e degradazione graziosa se il
modello non è installato. Sblocca **B1.1** (redazione dei nomi di terzi prima
dell'LLM, ora fattibile riusando `/v1/ner`).

**Perché.** Riduce gli alert HITL per omonimia irrisolta. L'Entity Resolution usa
oggi match deterministico (CF/P.IVA) + similarità sul nome normalizzato: i casi
senza identificatore forte finiscono in revisione umana
(`ambiguous`/`needs_review`).

**Scope.**
- **NER** (modello IT) per estrarre persone/organizzazioni dagli articoli →
  corroborazione più robusta dell'attuale `mention.check` (oltre il match di
  stringa su azienda/località/ruolo);
- **Embedding** per similarità semantica di nome/contesto, oltre la similarità di
  stringa in `normalize.py`.

**Componenti.** `services/entity-resolution` (`normalize.py`, `resolver.py`);
`services/worker-scraping/app` (`mention.py`).

**Sinergie.** Alimenta B1 (redazione PII robusta via NER) e B5 (materialità).

**Definition of Done.** Riduzione **misurabile** degli alert HITL su un set di
test, senza aumento dei falsi positivi di attribuzione.

## B8 — Multi-provider fan-out della ricerca · P2

**Stato: ✅ FATTO.** `SEARCH_PROVIDER` accetta una lista (es. `searxng,gdelt,brave`):
fan-out parallelo (`asyncio.gather`) con timeout per provider, merge + dedup per
URL, boost di corroborazione (URL da più motori in cima; `provider="a+b"`,
`corroborations=n`). Nuovo provider **SearXNG** (self-hosted, keyless) + servizio
nel compose con JSON API abilitata. Postprocessing (credibilità/dedup dominio)
invariato. Singolo provider = comportamento di prima.

**Perché.** Oggi `SEARCH_PROVIDER` seleziona **un solo** motore per volta. Il
fan-out parallelo su più motori aumenta **recall** (unione degli indici),
**resilienza** (se uno va in 429/timeout gli altri coprono) e **corroborazione**
(lo stesso URL trovato da più motori è un segnale forte). Realizza lo schema
proposto (vedi diagramma) e l'analisi in
[`open_search_engines`](open_search_engines.md).

**Architettura obiettivo.**

```mermaid
flowchart LR
    REQ["POST /v1/search"] --> FAN["Fan-out<br/>parallelo"]
    FAN --> P1["SearXNG"]
    FAN --> P2["GDELT"]
    FAN --> P3["Brave"]
    FAN --> P4["MediaCloud"]
    P1 --> MERGE["Merge +<br/>Dedup URL"]
    P2 --> MERGE
    P3 --> MERGE
    P4 --> MERGE
    MERGE --> PP["Postprocessing<br/>(credibilità, dedup<br/>dominio, filtro)"]
    PP --> RES["Risposta<br/>unificata"]
```

**Scope.**
- `SEARCH_PROVIDER` accetta una **lista** (es. `searxng,gdelt,brave,mediacloud`);
- fan-out con `asyncio.gather`, **timeout per provider** e degradazione graziosa
  (se tutti falliscono → `mock`);
- **merge + dedup per URL**, **boost di corroborazione** (URL da 2+ motori sale di
  ranking), **annotazione provider** (`provider: "gdelt+brave"`) per tracciabilità;
- **postprocessing invariato** (credibilità testata, dedup per dominio, filtro);
- ogni provider mantiene la **propria sintassi** di query (`boolean` per GDELT,
  `plain` per Brave/SearXNG) — già gestita da `build_query_variants(..., syntax=)`.

**Motori prioritari** (dall'analisi allegata):
- **SearXNG** — meta-search self-hosted (Google/Bing/DuckDuckGo News…), primario:
  niente chiave, niente rate-limit upstream centralizzato, container ufficiale;
- **MediaCloud** — news con metadati ricchi e filtri IT/testata (allineato al caso
  adverse media);
- poi, come arricchimento/diversificazione: **Newscatcher**, **Mojeek** (indice
  indipendente), **Marginalia** (siti istituzionali di nicchia), **Common Crawl**
  (retrospettivo, non real-time).

**Componenti.** `services/search-gateway/app/providers.py` (`search()`),
`app/config.py`, `docker-compose.dev.yml` (servizio `searxng`).

**Definition of Done.** Query con 2+ provider in parallelo; risultati fusi e
dedotti per URL; corroborazione riflessa nel ranking; il singolo-provider resta
supportato per compatibilità.

## B9 — Feed di rischio strutturato (Crime&tech) · P2

**Stato: ✅ SCAFFOLDING (default OFF, non collegato).** Creata l'astrazione
`services/risk-gateway` (nuovo microservizio, porta 8096) come **punto unico di
egress** verso provider di dati di rischio, analoga a `search-gateway`/
`llm-gateway`. Include: dispatch provider (`RISK_PROVIDER`: `""`=OFF | `mock` |
`crimetech`), **mappatura** indicatori→FATF/severità e connessioni→driver/
evidenza (`app/mapping.py`, pura e testata), **client Crime&tech stub**
(`app/crimetech.py`, endpoint documentato, guardie hard anti-egress), provider
**mock** con fixture per il collaudo offline, e l'aggancio nel workflow
(`assess_risk_feed` **dopo** l'Entity Resolution). Test 9/9. Dettaglio e
attivazione in [`CRIMETECH_FEED`](CRIMETECH_FEED.md).

**Perché.** Il feed **non** è web search: è una fonte **per identità** (dato il
soggetto risolto, restituisce indicatori di rischio validati per tipo di reato,
con rating esplicabile, e la **rete di connessioni**). Complementare all'adverse
media: alza l'AMI anche quando gli articoli tacciono, e porta segnali di rete
(soci/consulenti a rischio) che la ricerca testuale non vede.

**Architettura.** Endpoint documentato di riferimento
`GET /dataset/{dataset_id}/risk-indicators/{entity_id}/connections`. Flusso:
Entity Resolution → **riconciliazione** soggetto→`entity_id` nel dataset del
provider → fetch indicatori+connessioni → mappa su FATF/AMI/evidenza → arricchisce
l'alert. Collocato **dopo** il gate: si interroga solo un'identità certa.

```mermaid
flowchart LR
    ER["Entity Resolution<br/>(gate)"] --> RG["risk-gateway<br/>/v1/risk"]
    RG --> REC["Riconciliazione<br/>entity_id"]
    REC --> CT["Crime&tech<br/>indicatori + connessioni"]
    CT --> MAP["Mappatura<br/>FATF / severità / evidenza"]
    MAP --> AMI["AMI + driver<br/>dell'alert"]
```

**Vincoli (compliance).** A differenza dell'adverse media, la **redazione PII
non è applicabile**: per interrogare il feed si invia l'**identità reale** a un
processore esterno. Prerequisiti all'attivazione: **spec OpenAPI** ufficiale +
**chiave** (mai nel repo), **licenza/DPA**, **DPIA** aggiornata (nuovo
trasferimento di dati personali), base giuridica del trattamento. Le due guardie
`CRIMETECH_LIVE` + `CRIMETECH_API_KEY` impediscono qualunque egress finché non
sono entrambe valorizzate; oggi l'egress verso `api.crimetech.app` è comunque
bloccato dal proxy dell'ambiente.

**Componenti.** `services/risk-gateway` (nuovo); `services/worker-scraping`
(`assess_risk_feed`, hook nel workflow); `docker-compose.dev.yml` (servizio
`risk-gateway`); catalogo Fonti (riga `crimetech`, `sospesa`).

**Definition of Done (per l'attivazione).** Reconcile entità→`entity_id`
implementato sullo schema reale; `_normalize_connections_response` confermata
sui campi OpenAPI; DPIA/DPA firmati; un soggetto noto produce indicatori+
connessioni mappati in AMI/driver, con test su risposta reale (oggi: mock).
