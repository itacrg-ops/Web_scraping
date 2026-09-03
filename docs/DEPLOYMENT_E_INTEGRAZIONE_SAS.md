# Deployment e Integrazione SAS Viya — Architettura a container
## Adverse Media Screening FSC/MASE

> **Documento di architettura** · Deployment cloud-native e integrazione con SAS Viya
> Versione: 1.0 · Settembre 2026
> Prerequisito: [documento tecnico-funzionale v1.1](WebScraping_AdverseMedia_FSC_MASE.md)

### Decisioni di base (fissate)
- **Orchestrazione LLM/embedding → Microsoft Azure AI Foundry** (modelli gestiti; nessun node pool GPU nel nostro cluster).
- **SAS Viya esterna/gestita**: integrazione *via rete*; nel nostro cluster gira il solo container **`sas-mcp-server`** che punta a `VIYA_ENDPOINT`.
- **Runtime**: container Docker, **portabili su Kubernetes** (parità dev↔prod, 12-factor).
- **Orchestratore workflow**: **Temporal** (esecuzione durevole, retry idempotenti, auditabilità) — vedi §3. Alternativa più leggera: Celery+Redis.

---

## Indice
1. [Obiettivi e principi](#1-obiettivi-e-principi)
2. [Vista d'insieme](#2-vista-dinsieme)
3. [Catalogo dei container](#3-catalogo-dei-container)
4. [Scalabilità](#4-scalabilità)
5. [Dati, stato e storage](#5-dati-stato-e-storage)
6. [Networking, sicurezza e segreti](#6-networking-sicurezza-e-segreti)
7. [Integrazione SAS Viya via SAS MCP server](#7-integrazione-sas-viya-via-sas-mcp-server)
8. [Integrazione LLM via Azure AI Foundry](#8-integrazione-llm-via-azure-ai-foundry)
9. [Portabilità Docker → Kubernetes](#9-portabilità-docker--kubernetes)
10. [Osservabilità e audit](#10-osservabilità-e-audit)
11. [CI/CD e supply chain](#11-cicd-e-supply-chain)
12. [Rollout dei container per fase](#12-rollout-dei-container-per-fase)
13. [Punti aperti da confermare](#13-punti-aperti-da-confermare)
- [Appendice A — Compose di sviluppo (illustrativo)](#appendice-a--compose-di-sviluppo-illustrativo)
- [Appendice B — Variabili d'ambiente chiave](#appendice-b--variabili-dambiente-chiave)

---

## 1. Obiettivi e principi

- **Un servizio = un container = un processo** (12-factor): configurazione via ambiente, segreti esterni, log su stdout, processi *stateless* dove possibile.
- **Disaccoppiamento via coda**: produttori (ingestion) e consumatori (agenti) scalano in modo indipendente; la profondità della coda è il segnale di autoscaling primario.
- **Isolamento per profilo di risorsa**: i componenti pesanti (browser headless, inferenza) hanno deployment e node pool dedicati, così un picco di scraping non affama l'API.
- **Portabilità**: la stessa immagine gira in Docker Compose (dev) e in Kubernetes (test/prod); nessuna dipendenza dall'infrastruttura nel codice.
- **Sicurezza e sovranità del dato (PA)**: default-deny di rete, egress su allow-list, identità federata al posto di chiavi statiche, dati in UE, cloud qualificato ACN.
- **Minimizzazione verso l'esterno**: verso Azure e SAS escono solo i dati strettamente necessari (vedi §7.5 e §8.3); il testo giudiziario grezzo resta nel perimetro controllato.

---

## 2. Vista d'insieme

```
                              INTERNET (egress allow-list)
        ┌───────────────┬───────────────────────┬───────────────────────┐
        │               │                       │                       │
   Fonti web/news   Azure AI Foundry        SAS Viya (esterna)        PDND / ANAC /
   (scraping)       (LLM + embedding)       (REST + CAS)              InfoCamere / BDU
        ▲               ▲                       ▲                       ▲
        │egress         │HTTPS                  │HTTPS                  │mTLS/OAuth
╔═══════╪═══════════════╪═══════════════════════╪═══════════════════════╪═══════════════╗
║  KUBERNETES CLUSTER (namespace: adverse-media-{env})     [cloud qualificato ACN/PSN]  ║
║       │               │                       │                       │               ║
║  ┌────┴─────┐   ┌──────┴──────┐         ┌──────┴───────┐        ┌──────┴───────┐       ║
║  │ Ingress  │   │ llm-gateway │         │ sas-mcp-     │        │ ingestion-   │       ║
║  │ (TLS)    │   │ (Foundry)   │         │ server (HTTP)│        │ connectors   │       ║
║  └────┬─────┘   └──────┬──────┘         └──────┬───────┘        └──────┬───────┘       ║
║       │                │                       │                       │               ║
║  ┌────┴─────┐    ┌──────┴──────────────────────┴───────────────────────┴────────┐     ║
║  │  api     │    │        TEMPORAL  (server + task queues)                       │     ║
║  │ (FastAPI)│◀──▶│  workers per profilo di risorsa:                             │     ║
║  │  + HITL  │    │  entity-res · scraping/browser · extraction · classification │     ║
║  │   UI     │    │  · ami-scoring · conflict/HITL                               │     ║
║  └────┬─────┘    └───────────────────────────────┬──────────────────────────────┘     ║
║       │                                          │                                     ║
║  ┌────┴──────────────── STATO (StatefulSet / operator / managed) ──────────────┐      ║
║  │  PostgreSQL(+pgvector) · Neo4j · Redis · Object store WORM (WARC/HTML)        │      ║
║  └──────────────────────────────────────────────────────────────────────────────┘      ║
║  ┌──────────── OSSERVABILITÀ ────────────┐   ┌──────── AUDIT immutabile ────────┐      ║
║  │ otel-collector · metrics · logs · trace│   │ append-only + WORM + eIDAS TS    │      ║
║  └────────────────────────────────────────┘   └──────────────────────────────────┘      ║
╚═══════════════════════════════════════════════════════════════════════════════════════╝
```

Confini chiave: **niente GPU nel cluster** (l'inferenza è su Azure Foundry); **SAS Viya è fuori** (dentro c'è solo il suo gateway MCP); **gli store con stato** sono gestiti/operator, non processi effimeri.

---

## 3. Catalogo dei container

Legenda scaling: **SL** = stateless (scala in orizzontale) · **ST** = stateful (scala in verticale / repliche gestite).

| # | Container | Ruolo | Tipo | Autoscaling |
|---|-----------|-------|------|-------------|
| 1 | **ingress** | Terminazione TLS, routing (nginx/Contour) | SL | HPA su connessioni |
| 2 | **api** | Backend FastAPI: alert, gestione workflow, azioni HITL, API per la UI | SL | HPA su CPU/RPS |
| 3 | **hitl-ui** | Interfaccia investigativa per il I livello (SPA servita statica) | SL | HPA su CPU |
| 4 | **temporal-server** | Orchestratore durevole (frontend/history/matching) | ST¹ | Repliche fisse / Temporal Cloud |
| 5 | **worker-entity-resolution** | Anti-omonimia: normalizzazione, matching CF/P.IVA/CUP, NER (spaCy/BERT) | SL | KEDA su coda |
| 6 | **worker-scraping** | Fetcher HTTP (IO-bound), rispetto robots/ToS/opt-out TDM, politeness | SL | KEDA su coda |
| 7 | **browser-pool** | Chromium headless (Playwright) per pagine dinamiche — pesante | SL² | KEDA su coda, cap repliche |
| 8 | **worker-extraction** | Boilerplate removal, estrazione testo/metadati, deduplica, filtro lingua/pertinenza | SL | KEDA su coda |
| 9 | **worker-classification** | Classificazione FATF dual-LLM via llm-gateway; ruolo processuale | SL | KEDA su coda (cap = quota Foundry) |
| 10 | **worker-ami-scoring** | Calcolo AMI; chiama SAS Viya (`score_data`) via sas-mcp-server; SHAP | SL | KEDA su coda |
| 11 | **worker-conflict-hitl** | Conflict resolution, soglie, escalation al I livello | SL | KEDA su coda |
| 12 | **ingestion-connectors** | Connettori PDND/ANAC/InfoCamere/OpenCoesione/BDU (batch e API) | SL | CronJob / KEDA |
| 13 | **llm-gateway** | Gateway verso Azure AI Foundry: routing dual-LLM, rate-limit, retry/backoff, **redazione PII**, logging, caching, token accounting | SL | HPA su RPS |
| 14 | **sas-mcp-server** | Immagine ufficiale `ghcr.io/sassoftware/sas-mcp-server` (HTTP mode) verso SAS Viya | SL | HPA su RPS |
| 15 | **sas-token-broker** | Ottiene/rinnova il token SASLogon (service account) per le chiamate MCP | SL³ | 1-2 repliche |
| 16 | **postgresql (+pgvector)** | Dati strutturati + vettori (near-duplicate / retrieval) | ST | Operator (CloudNativePG) / managed |
| 17 | **neo4j** | Knowledge graph (alias, UBO, relazioni) — da Rilascio 3 | ST | Verticale / cluster causale |
| 18 | **redis** | Cache, rate-limit counters, hash di dedup (broker se Celery) | ST | Verticale / repliche |
| 19 | **object-store (MinIO/S3)** | Snapshot WARC/HTML immutabili (WORM/object-lock) | ST | Managed S3 / MinIO operator |
| 20 | **otel-collector** | Raccolta trace/metric/log (OpenTelemetry) | SL | DaemonSet/Deployment |
| 21 | **audit-sink** | Log immutabile append-only delle disposizioni (WORM, marca temporale eIDAS) | ST | Managed / operator |

¹ *Temporal* richiede un datastore proprio (Postgres/Cassandra); in alternativa **Temporal Cloud** (gestito) azzera l'onere operativo.
² il *browser-pool* è stateless ma **memory-heavy**: limiti risorse stringenti, `PodDisruptionBudget`, node pool dedicato.
³ può essere una *sidecar*/libreria anziché un servizio a sé; isolato per contenere le credenziali SAS.

> **Nota di semplificazione MVP.** Il Rilascio 1 non richiede tutto: bastano `api`, `hitl-ui`, `temporal-server`, `worker-entity-resolution`, `worker-scraping`+`browser-pool`, `worker-extraction`, `postgresql`, `redis`, `object-store`, `otel-collector`. Classificazione/AMI/SAS/Neo4j entrano nei rilasci successivi (§12).

---

## 4. Scalabilità

### 4.1 Principio: scalare sulla coda, non solo sulla CPU
Il carico di screening è **bursty** (arrivi a lotti per CUP/programma). L'autoscaling su CPU reagisce tardi; usiamo **KEDA** con trigger sulla **profondità della task queue Temporal** (o della coda Celery). Ogni tipo di lavoro ha la sua coda → i pool scalano indipendentemente.

### 4.2 Profili di risorsa e node pool
| Profilo | Container | Node pool |
|---------|-----------|-----------|
| Generale (IO-bound) | api, worker-scraping, classification, ami, connectors, gateway, mcp | `general` |
| Memory-heavy | **browser-pool** | `browser` (limiti alti, cap repliche) |
| CPU-bound | entity-resolution (NER), extraction | `compute` |
| Stateful | postgres, neo4j, redis, object-store | `data` (dischi veloci) |

**Niente node pool GPU**: l'inferenza LLM/embedding è su Azure Foundry. Questo è un risparmio operativo diretto della scelta Foundry.

### 4.3 Backpressure e limiti
- **worker-classification**: la concorrenza massima è vincolata dalle **quote TPM/RPM di Azure Foundry**; il `llm-gateway` applica rate-limit e coda in ingresso per non superare la quota (evita 429 a cascata).
- **browser-pool**: cap sulle repliche (Chromium consuma ~centinaia di MB per contesto); oltre il cap, la coda assorbe il picco.
- **sas-mcp-server / SAS Viya**: la capacità di scoring lato Viya è finita; rate-limit lato gateway e circuit breaker sul worker-ami.
- **Cluster autoscaler** aggiunge nodi quando i pool saturano; `PodDisruptionBudget` protegge i lavori in corso durante gli upgrade.

### 4.4 Idempotenza (prerequisito per scalare)
Ogni attività è **idempotente** (chiave = hash del contenuto + versione modello) così i retry di Temporal e le repliche concorrenti non duplicano evidenze o alert. È già un requisito del documento tecnico (§4.4).

---

## 5. Dati, stato e storage

| Store | Contenuto | Note di deployment |
|-------|-----------|--------------------|
| **PostgreSQL** | Subject, Evidence, Classification, AMI, Alert, audit strutturato | Operator (CloudNativePG) con repliche read + backup PITR, oppure DB managed |
| **pgvector** | Embedding per near-duplicate e retrieval | Estensione su Postgres (evita un DB vettoriale separato all'inizio) |
| **Neo4j** | Grafo alias/UBO/relazioni | Solo da Rilascio 3; cluster causale se serve HA |
| **Redis** | Cache, contatori rate-limit, hash dedup | Persistenza opzionale; se Celery, anche broker |
| **Object store (MinIO/S3)** | Snapshot WARC/HTML (evidenza) | **Object-lock/WORM** + retention; immutabilità probatoria |
| **Audit sink** | Disposizioni, versioni modello/decisione, chi/quando | Append-only, WORM, marca temporale **eIDAS** |

**Regola**: gli store con stato **non** sono processi effimeri del deployment applicativo — vanno su operator o servizi gestiti, con backup e disaster recovery propri. Le immagini applicative restano interamente stateless.

---

## 6. Networking, sicurezza e segreti

- **NetworkPolicy default-deny**; aperture esplicite: solo `worker-ami` e `worker-conflict` raggiungono `sas-mcp-server`; solo i worker LLM raggiungono `llm-gateway`; solo `llm-gateway` ha egress verso Azure; solo `sas-mcp-server`/`sas-token-broker` hanno egress verso `VIYA_ENDPOINT` e SASLogon.
- **Egress allow-list** (egress gateway): endpoint Azure Foundry, SAS Viya, PDND/ANAC/InfoCamere, e i domini di scraping autorizzati. Tutto il resto è bloccato.
- **Identità federata, non chiavi statiche**: verso Azure Foundry si usa **Workload Identity Federation** (il ServiceAccount K8s ottiene token Azure senza secret persistiti). Verso SAS, service account SASLogon con token a vita breve gestiti dal `sas-token-broker`.
- **Segreti**: External Secrets Operator / Vault / KMS del cloud; nessun segreto in immagini o `ConfigMap`.
- **TLS ovunque**: ingress (cert-manager) e, dove supportato, mTLS interno (service mesh opzionale, es. Linkerd) per i percorsi che toccano dati giudiziari.
- **Immagini**: non-root, filesystem read-only, `securityContext` restrittivo, `seccomp`; il browser-pool gira in sandbox con capacità minime.
- **Dati in UE**, cloud qualificato ACN/PSN; classificazione del dato e misure minime AgID.

---

## 7. Integrazione SAS Viya via SAS MCP server

### 7.1 Componente
Immagine ufficiale **`ghcr.io/sassoftware/sas-mcp-server`** eseguita in **HTTP mode** (endpoint `/mcp`, porta 8134). È *stateless* → scalabile in orizzontale dietro il Service. SAS fornisce anche Helm chart/manifests di riferimento (ingress Contour/nginx, TLS).

### 7.2 Chi chiama chi
```
worker-ami-scoring / worker-conflict-hitl   (MCP client)
                    │  HTTP /mcp  (in-cluster, mTLS)
                    ▼
             sas-mcp-server            ── Authorization: Bearer <token SASLogon> (ALLOW_RAW_BEARER)
                    │  REST + CAS
                    ▼
              SAS Viya (esterna)  →  Model Manager · Intelligent Decisioning · CAS
```

### 7.3 Autenticazione (service-to-service, non interattiva)
Il flusso OAuth2/PKCE del MCP server è pensato per un umano con browser. Per un servizio usiamo il pattern **raw bearer**:
1. `sas-token-broker` si autentica a **SASLogon** con un **service account** (client credentials / technical user) e ottiene un access token OAuth a vita breve.
2. Il worker chiama `sas-mcp-server` con `Authorization: Bearer <token>`; il server, avviato con **`ALLOW_RAW_BEARER=true`**, lo inoltra a SAS Viya.
3. Il broker rinnova i token prima della scadenza; nessuna password persistita.

### 7.4 Privilegio minimo (due profili di deployment)
Il MCP server espone 75 tool su 9 tier: li restringiamo con `MCP_TIERS` e `MCP_READ_ONLY`.

| Istanza | Uso | Configurazione |
|---------|-----|----------------|
| **`sas-mcp-runtime`** | Hot path in produzione: solo scoring/lettura | `MCP_TIERS=6` + `MCP_READ_ONLY=true` (es. `score_data`, `list_registered_models`) |
| **`sas-mcp-govops`** | Solo a tempo di governance/deploy: registrazione modelli e pubblicazione decisioni | `MCP_TIERS=5,6,7`, credenziali separate, accesso ristretto agli operatori |

Così il percorso runtime **non può** modificare modelli o regole: può solo **consumare** decisioni e scoring già governati.

### 7.5 Cosa fa SAS Viya nell'architettura
- **Model Management & Scoring (Tier 6)**: registra, versiona e **monitora** il modello di **AMI scoring** e i modelli di supporto/monitoraggio del classificatore FATF (drift, champion/challenger, accuratezza — art. 15 AI Act). Il worker-ami invoca `score_data` sul modello campione governato.
- **Intelligent Decisioning (Tier 7)**: le **regole deterministiche** (doppio finanziamento via CUP, red flag) e la **mappatura soglia→disposizione** (auto-chiusura vs escalation) vivono come **business ruleset / decision flow** versionati e auditabili in Viya. È la traduzione governata del requisito "niente scoring black-box: spiegabile e tracciabile", e il punto di innesto nei flussi antifrode esistenti.
- **HITL preservato**: la decisione SAS produce una **raccomandazione** di disposizione; la determinazione resta all'istruttore (nessun effetto giuridico automatico).

### 7.6 Minimizzazione dei dati verso SAS
Verso SAS Viya inviamo **feature e segnali derivati** (categoria FATF, severità, confidence, materialità vs CUP, ruolo, flag red-flag), **non** il testo grezzo degli articoli giudiziari. La lettura del testo avviene nel `worker-classification` via Azure gateway; a valle, solo l'output strutturato attraversa il confine. Confine di compliance netto e difendibile.

### 7.7 Audit
Ogni chiamata MCP è registrata nell'audit sink: tool invocato, hash degli input, **versione del modello/decisione**, risposta, timestamp. Si somma alla natura "governata e auditabile" già propria del MCP server.

---

## 8. Integrazione LLM via Azure AI Foundry

### 8.1 llm-gateway (punto unico di governo)
Tutti i worker che usano LLM/embedding passano dal **`llm-gateway`** interno (può basarsi su un proxy tipo LiteLLM). Responsabilità:
- **Routing dual-LLM**: modello primario e secondario per la classificazione FATF (il gateway astrae i deployment Foundry).
- **Rate-limit e backpressure** allineati alle quote TPM/RPM di Foundry; retry con backoff su 429/5xx.
- **Redazione/minimizzazione PII** prima dell'invio; **logging** dei prompt/risposte (hash) per audit e riproducibilità.
- **Caching** semantico per abbattere costi e latenza sui near-duplicate.
- **Token/cost accounting** per soggetto/CUP.

### 8.2 Autenticazione
**Workload Identity Federation**: il ServiceAccount K8s del gateway ottiene token Azure senza chiavi statiche in cluster (niente API key da ruotare a mano).

### 8.3 Residenza dati e compliance (da validare in DPIA)
- **Regione UE** (es. *Italy North* / *Sweden Central*) e adesione all'**EU Data Boundary** di Microsoft; DPA con impegno di **non addestramento** sui nostri input.
- **Dato sensibile (art. 10 GDPR)**: l'invio di testo potenzialmente giudiziario a un provider cloud non-UE (ancorché con hosting UE) è un punto da **valutare esplicitamente in DPIA/FRIA**; la redazione PII (§8.1) e la minimizzazione riducono l'esposizione. Alternativa di fallback: inferenza on-prem se la DPIA lo richiede (l'astrazione del gateway rende il cambio a costo contenuto).
- **Egress** solo verso gli endpoint Foundry (allow-list).

---

## 9. Portabilità Docker → Kubernetes

- **Parità di ambiente**: stessa immagine per dev (Docker Compose) e test/prod (Kubernetes); solo la configurazione cambia (env + segreti).
- **Immagini**: multi-stage, base *slim*/distroless, non-root, versioni **pinnate a digest**, un processo per container.
- **Config**: 12-factor — nessun valore d'ambiente hard-coded; `ConfigMap` per la config non sensibile, secret manager per il resto.
- **Probe**: `liveness`/`readiness`/`startup` per ogni servizio; i worker gestiscono **SIGTERM** per completare i task in volo (graceful shutdown).
- **Manifests**: **Helm** (o Kustomize) con `values` per ambiente; il chart del `sas-mcp-server` fornito da SAS si innesta come dipendenza.
- **Ambienti**: namespace separati `adverse-media-{dev,test,prod}`; RBAC e quote per namespace.
- **Storage**: `PVC` per gli stateful; bucket con object-lock per gli snapshot.

Il percorso è: **Compose in locale → Helm su Kubernetes** senza modifiche al codice, solo ai valori.

---

## 10. Osservabilità e audit

- **OpenTelemetry** end-to-end: un `trace_id` segue il soggetto lungo tutta la pipeline (scraping → estrazione → classificazione → AMI → disposizione), incluse le chiamate a `llm-gateway` e `sas-mcp-server`.
- **Metriche**: profondità code, latenza per stadio, tasso 429 Foundry, tempi Viya, throughput soggetti/ora.
- **Log strutturati** su stdout → collector → backend (Loki/managed).
- **Audit immutabile** separato dai log operativi: append-only, **WORM**, marca temporale eIDAS; contiene ogni disposizione con evidenze, versioni e (se presente) operatore.

---

## 11. CI/CD e supply chain

Per una PA che tratta dati giudiziari la **catena di fornitura** è essa stessa un requisito di sicurezza:
- Build riproducibili; **SBOM** per immagine; scansione vulnerabilità (Trivy/Grype) in CI con gate.
- **Firma immagini** (cosign) e verifica in admission (policy) — solo immagini firmate girano in cluster.
- Registry privato; nessun `latest`, solo digest.
- Pipeline per ambiente (dev/test/prod) con promozione controllata; migrazioni DB come job idempotenti.
- Il `sas-mcp-server` si consuma dall'immagine ufficiale `ghcr.io/sassoftware/...` **pinnata a digest** e ri-scansionata.

---

## 12. Rollout dei container per fase

Allineato al piano di sviluppo del documento tecnico (§9):

| Fase | Container introdotti |
|------|----------------------|
| **Avvio** | CI/CD, registry, ambienti; scheletro `api`; `postgres`, `redis`, `object-store`, `otel-collector` |
| **Rilascio 1** (MVP) | `hitl-ui`, `temporal-server`, `worker-entity-resolution`, `worker-scraping`, `browser-pool`, `worker-extraction`, `ingestion-connectors`, `audit-sink` |
| **Rilascio 2** | `llm-gateway` (Azure Foundry), `worker-classification`, `worker-ami-scoring`, `worker-conflict-hitl`, `sas-mcp-server` (+`sas-token-broker`) |
| **Rilascio 3** | `neo4j` e worker di network analysis; hardening, monitoraggio drift/bias |

Così l'infrastruttura cresce col valore: l'MVP non paga il costo operativo di SAS, LLM o grafo finché non servono.

---

## 13. Punti aperti da confermare

1. **Temporal self-hosted vs Temporal Cloud** — Cloud riduce l'onere operativo (no datastore Temporal da gestire) ma è un servizio esterno da valutare per residenza/qualificazione.
2. **Regione Azure Foundry** (Italy North vs Sweden Central) e conferma **EU Data Boundary** + DPA no-training, in DPIA/FRIA.
3. **Ammissibilità dell'invio di testo giudiziario a Foundry** (§8.3): esito della DPIA; eventuale fallback on-prem.
4. **Cloud target** (PSN/ACN-qualificato) e vincoli di rete verso SAS Viya e PDND.
5. **Service account SASLogon**: creazione del technical user, tier e scope concessi, policy di rotazione token.
6. **Object store**: MinIO in-cluster vs S3 gestito (per WORM/retention e DR).
7. **Service mesh** (mTLS interno) sì/no per i percorsi con dati giudiziari.

---

## Appendice A — Compose di sviluppo (illustrativo)

> Snippet di riferimento per l'ambiente locale (non ancora materializzato nel repo: lo scaffolding sarà un passo successivo). Le immagini reali dei worker verranno costruite dal progetto.

```yaml
# docker-compose.dev.yml (bozza illustrativa)
services:
  api:
    build: ./services/api
    env_file: .env
    ports: ["8000:8000"]
    depends_on: [postgres, redis, temporal]

  temporal:
    image: temporalio/auto-setup:1.25.0   # dev; in prod: server + datastore dedicato
    ports: ["7233:7233"]

  worker-scraping:
    build: ./services/worker-scraping
    env_file: .env
    depends_on: [temporal, redis]

  browser-pool:
    build: ./services/browser-pool         # Playwright/Chromium
    shm_size: "1gb"
    env_file: .env

  llm-gateway:
    build: ./services/llm-gateway          # verso Azure AI Foundry
    env_file: .env

  sas-mcp-server:
    image: ghcr.io/sassoftware/sas-mcp-server:<digest>
    environment:
      VIYA_ENDPOINT: ${VIYA_ENDPOINT}
      ALLOW_RAW_BEARER: "true"
      MCP_TIERS: "6"
      MCP_READ_ONLY: "true"
    ports: ["8134:8134"]

  postgres:
    image: postgres:16                      # + estensione pgvector
    environment: { POSTGRES_PASSWORD: ${POSTGRES_PASSWORD} }
    volumes: ["pgdata:/var/lib/postgresql/data"]

  redis:
    image: redis:7

  minio:
    image: minio/minio                      # object store S3-compatibile (WARC)
    command: server /data
    volumes: ["minio:/data"]

volumes: { pgdata: {}, minio: {} }
```

## Appendice B — Variabili d'ambiente chiave

**sas-mcp-server**
| Variabile | Valore tipico | Note |
|-----------|---------------|------|
| `VIYA_ENDPOINT` | `https://viya.ente.it` | URL della Viya esterna |
| `VIYA_AUTH` | `true` | **mai** `false` in PA |
| `ALLOW_RAW_BEARER` | `true` | abilita il pattern service-to-service |
| `MCP_TIERS` | `6` (runtime) / `5,6,7` (govops) | privilegio minimo |
| `MCP_READ_ONLY` | `true` (runtime) | 43 tool read-only |
| `MCP_LANDING_PAGE` | `false` | nessuna landing non autenticata |

**llm-gateway (Azure AI Foundry)**
| Variabile | Note |
|-----------|------|
| `AZURE_FOUNDRY_ENDPOINT` | endpoint del progetto Foundry (regione UE) |
| `AZURE_TENANT_ID` / federated identity | Workload Identity Federation (no chiavi statiche) |
| `LLM_MODEL_PRIMARY` / `LLM_MODEL_SECONDARY` | deployment dual-LLM |
| `EMBEDDING_MODEL` | modello di embedding |
| `LLM_MAX_TPM` / `LLM_MAX_RPM` | allineati alla quota Foundry (backpressure) |

---

*Documento di architettura — uso interno. I riferimenti a componenti di terze parti (SAS MCP server, Azure AI Foundry) vanno verificati sulle versioni effettivamente adottate; le scelte di residenza e trattamento dati vanno validate in DPIA/FRIA con legale/DPO.*
