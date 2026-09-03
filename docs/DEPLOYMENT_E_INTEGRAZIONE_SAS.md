# Deployment e Integrazione SAS Viya — Architettura a container
## Adverse Media Screening FSC/MASE

> **Documento di architettura** · Deployment cloud-native e integrazione con SAS Viya
> Versione: **1.1** · Settembre 2026 · (modifiche v1.0→v1.1 in [Appendice C](#appendice-c--changelog))
> Prerequisito: [documento tecnico-funzionale v1.1](WebScraping_AdverseMedia_FSC_MASE.md)

### Decisioni di base (fissate)
- **Cloud target: Microsoft Azure** (stesso account/tenant di Foundry), orchestrazione con **AKS** (Azure Kubernetes Service) → vedi §11.
- **Orchestrazione LLM/embedding → Microsoft Azure AI Foundry** (modelli gestiti; nessun node pool GPU nel nostro cluster).
- **SAS Viya esterna/gestita**: integrazione *via rete*; nel nostro cluster gira il solo container **`sas-mcp-server`** che punta a `VIYA_ENDPOINT`.
- **Separazione netta front-end / back-end** (§3): il front-end è una SPA che parla **solo** con l'API; nessun accesso diretto a dati, LLM o SAS.
- **Front-end: React + TypeScript**, avvio *admin-first* con **Refine**, crescita verso la console HITL investigativa (§4).
- **Orchestratore workflow**: **Temporal** (esecuzione durevole, retry idempotenti, auditabilità). Alternativa leggera: Celery+Redis.

---

## Indice
1. [Obiettivi e principi](#1-obiettivi-e-principi)
2. [Vista d'insieme](#2-vista-dinsieme)
3. [Separazione front-end / back-end](#3-separazione-front-end--back-end)
4. [Framework front-end](#4-framework-front-end)
5. [Catalogo dei container](#5-catalogo-dei-container)
6. [Scalabilità](#6-scalabilità)
7. [Dati, stato e storage](#7-dati-stato-e-storage)
8. [Networking, sicurezza e segreti](#8-networking-sicurezza-e-segreti)
9. [Integrazione SAS Viya via SAS MCP server](#9-integrazione-sas-viya-via-sas-mcp-server)
10. [Integrazione LLM via Azure AI Foundry](#10-integrazione-llm-via-azure-ai-foundry)
11. [Deployment su Azure (servizi gestiti)](#11-deployment-su-azure-servizi-gestiti)
12. [Portabilità Docker → Kubernetes](#12-portabilità-docker--kubernetes)
13. [Osservabilità e audit](#13-osservabilità-e-audit)
14. [CI/CD e supply chain](#14-cicd-e-supply-chain)
15. [Rollout dei container per fase](#15-rollout-dei-container-per-fase)
16. [Punti aperti da confermare](#16-punti-aperti-da-confermare)
- [Appendice A — Compose di sviluppo (illustrativo)](#appendice-a--compose-di-sviluppo-illustrativo)
- [Appendice B — Variabili d'ambiente chiave](#appendice-b--variabili-dambiente-chiave)
- [Appendice C — Changelog](#appendice-c--changelog)

---

## 1. Obiettivi e principi

- **Un servizio = un container = un processo** (12-factor): configurazione via ambiente, segreti esterni, log su stdout, processi *stateless* dove possibile.
- **Front-end e back-end disaccoppiati**: cicli di rilascio, scaling e superficie di sicurezza indipendenti; l'API è l'unico confine di fiducia (§3).
- **Disaccoppiamento via coda**: produttori (ingestion) e consumatori (agenti) scalano in modo indipendente; la profondità della coda è il segnale di autoscaling primario.
- **Isolamento per profilo di risorsa**: i componenti pesanti (browser headless, inferenza) hanno deployment e node pool dedicati.
- **Portabilità prima del lock-in**: Kubernetes + Helm standard; i servizi gestiti Azure (§11) sono adottati per ridurre l'onere operativo ma restano **sostituibili** (documentati come tali).
- **Sicurezza e sovranità del dato (PA)**: default-deny di rete, traffico su **Private Endpoint** (backbone Azure, non Internet), **identità federata** al posto di chiavi statiche, dati in UE, cloud qualificato.
- **Minimizzazione verso l'esterno**: verso Azure e SAS escono solo i dati strettamente necessari (§9.6, §10.3).

---

## 2. Vista d'insieme

```
   Operatori I livello / Amministratori (browser)      Fonti web/news · Azure AI Foundry · SAS Viya · PDND
                    │ HTTPS + Entra ID                              ▲ (egress su allow-list / Private Endpoint)
╔═══════════════════╪═══════════════════════════════════════════════╪══════════════════════════════════════╗
║  AZURE  ·  AKS  ·  namespace adverse-media-{env}  ·  region UE (Italy North)                               ║
║   ┌───────────────┴───────────────┐                                                                        ║
║   │  FRONT-END TIER               │   Application Gateway / Front Door (WAF, TLS)                           ║
║   │  frontend (SPA React, nginx)  │                                                                         ║
║   └───────────────┬───────────────┘                                                                        ║
║                   │ REST/JSON (OpenAPI) + JWT      ◀── UNICO confine di fiducia                             ║
║   ┌───────────────┴───────────────────────────────────────────────────────────────────────────┐          ║
║   │  BACK-END TIER                                                                               │          ║
║   │  api (FastAPI: authz/RBAC, audit)  ·  TEMPORAL (server + task queues)                        │          ║
║   │  workers: entity-res · scraping/browser · extraction · classification · ami · conflict-hitl  │          ║
║   │  llm-gateway ─▶ Azure AI Foundry     sas-mcp-server ─▶ SAS Viya     ingestion-connectors ─▶ PDND        ║
║   └───────────────┬───────────────────────────────────────────────────────────────────────────┘          ║
║   ┌───────────────┴──── STATO (servizi gestiti Azure, §11) ─────────────────────────────────────┐         ║
║   │  Azure DB for PostgreSQL(+pgvector) · Azure Cache for Redis · Blob Storage (WORM) · Neo4j     │         ║
║   └───────────────────────────────────────────────────────────────────────────────────────────┘         ║
║   Identità: Entra ID (operatori) + AKS Workload Identity (servizi→Azure)   Segreti: Key Vault              ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## 3. Separazione front-end / back-end

### 3.1 Perché separarli (non è solo estetica)
Con dati potenzialmente giudiziari (art. 10 GDPR), la separazione è un **requisito di sicurezza**, non una preferenza:

- **L'API è l'unico confine di fiducia.** La SPA gira nel browser dell'operatore → è codice **non fidato**. Può parlare *solo* con l'API REST del back-end, che: autentica (JWT Entra ID), autorizza (RBAC), valida gli input, applica minimizzazione/redazione e **scrive l'audit trail** di ogni accesso al dato.
- **Il front-end non tocca mai** direttamente database, coda, object store, `llm-gateway` o `sas-mcp-server`. Questi sono interni al back-end e raggiungibili solo da esso (imposto via NetworkPolicy, §8). Il browser vede solo risposte API già governate.
- **Cicli e scaling indipendenti**: il front-end è un artefatto statico (build una volta, servito da nginx/CDN, cache all'edge); il back-end scala sulla computazione. Rilasci disaccoppiati.

### 3.2 Il confine
```
      Operatore I livello (browser)                 Amministratore (browser)
              │  HTTPS + Entra ID (MSAL)                    │
              ▼                                             ▼
   ┌────────────────────────── FRONT-END TIER ───────────────────────────┐
   │  frontend  (SPA React/TS · build statica servita da nginx)           │
   │   • Console HITL investigativa (alert, dossier, evidenze, grafo)     │
   │   • Console di amministrazione/configurazione                        │
   │  NESSUN accesso diretto a dati/DB/LLM/SAS — solo chiamate all'API    │
   └────────────────────────────────┬─────────────────────────────────────┘
                                     │  REST/JSON (contratto OpenAPI) + Bearer JWT
                                     ▼   ◀── qui si applicano authz, RBAC, validazione, AUDIT
   ┌────────────────────────── BACK-END TIER ────────────────────────────┐
   │  api (FastAPI)  →  Temporal, worker, llm-gateway, sas-mcp-server,     │
   │                    Postgres/pgvector, Neo4j, Redis, object store      │
   └──────────────────────────────────────────────────────────────────────┘
```

### 3.3 Autenticazione (due flussi distinti)
- **Operatori → front-end/API**: SSO con **Entra ID** (OIDC) via **MSAL** nella SPA; l'API valida il JWT e mappa i ruoli (I livello, amministratore, auditor). Se l'ente federa SASLogon con Entra, si ottiene un'unica identità end-to-end.
- **Servizi → Azure/SAS**: **Workload Identity** (federata) e token SASLogon di servizio — nessuna credenziale nel browser, nessuna chiave statica (§8, §9.3).
- **Opzione BFF**: per non esporre alcun token nel browser si può usare un *Backend-for-Frontend* con Authorization Code Flow + PKCE lato server (i cookie di sessione restano `HttpOnly`). Consigliato se la postura di sicurezza lo richiede.

### 3.4 Deployment del front-end
Tre opzioni, in ordine di portabilità:
1. **Container `frontend` (nginx) in AKS** — massima parità con il resto (stesso Helm/registry); ingress instrada `/` → frontend, `/api` → api. *Consigliato* per coerenza.
2. **Azure Static Web Apps** — hosting gestito della SPA + CDN/WAF integrati; meno da gestire, ma componente Azure a sé.
3. **Blob static hosting + Front Door** — statico su Blob dietro CDN/WAF.

---

## 4. Framework front-end

### 4.1 Serve un front-end dedicato?
**Sì.** Il documento tecnico pone l'**HITL** e il **dossier per il I livello** al centro: serve un'interfaccia investigativa vera (triage alert, lettura evidenze con provenienza, grafo relazioni, azioni di disposizione). Anche partendo da sole funzioni di amministrazione/configurazione, conviene una base che cresca fino alla console HITL **senza riscritture**.

### 4.2 Raccomandazione
| Livello | Scelta | Perché |
|---------|--------|--------|
| **Base** | **React + TypeScript + Vite** | Bacino di competenze più ampio (conta per handover/formazione in PA), ecosistema più ricco per UI dense di dati, supporto Entra ID di prima classe (MSAL) |
| **Acceleratore admin** | **Refine** (refine.dev) | Meta-framework React per tool interni: auth provider (MSAL/Entra), **RBAC**, data provider REST/OpenAPI, CRUD scaffolding. Fa uscire *subito* la console di config (registro fonti, soglie AMI, versioni modello, utenti/ruoli, viewer audit) e poi si estende con pagine custom per l'HITL — **stesso codebase** |
| **Libreria UI** | **MUI + MUI X (DataGrid)** | Maturo, accessibile (WCAG/AGID/L.4/2004), componenti enterprise (tabelle, filtri). AG Grid se il carico tabellare è molto pesante |
| **Dati/form** | **TanStack Query** · React Hook Form + Zod | Fetch/caching robusti; validazione tipizzata |
| **HITL (fase 2)** | Cytoscape.js / react-force-graph · viewer evidenze in iframe sandboxed · viewer PDF/OCR | Network analysis a grafo e lettura snapshot WARC in sicurezza |

**Percorso consigliato**: *admin-first con Refine → console HITL*. Si consegna valore amministrativo presto e si evita il big-bang della UI investigativa.

### 4.3 Alternativa minima (solo configurazione)
Se lo scope fosse **esclusivamente** configurazione/CRUD, si può evitare del tutto una SPA separata usando un admin **nativo FastAPI** — **Starlette-Admin** o **SQLAdmin** (server-rendered, zero build front-end). Meno parti in movimento, ma **non** copre l'HITL investigativo: adatto solo come stopgap. Data la centralità dell'HITL, **non è la scelta target**.

### 4.4 Perché non Angular/Vue
Entrambi validi. Angular è ottimo per grandi gestionali ma più pesante e con curva più ripida; Vue è snello ma con ecosistema "data-heavy" e integrazione Entra meno estesi di React. Per un prodotto che deve diventare una **console investigativa** e integrarsi con Entra, React è il compromesso migliore. La scelta può flettere sulle competenze del team.

---

## 5. Catalogo dei container

Legenda scaling: **SL** = stateless (scala in orizzontale) · **ST** = stateful (managed/operator).

| # | Container | Tier | Ruolo | Tipo | Autoscaling |
|---|-----------|------|-------|------|-------------|
| 1 | **frontend** | FE | SPA React (HITL + admin) servita da nginx | SL | HPA su CPU / o CDN |
| 2 | **ingress/WAF** | — | Application Gateway o Front Door (TLS, WAF, routing FE/BE) | — | gestito |
| 3 | **api** | BE | FastAPI: authz/RBAC, validazione, audit, API per la UI, avvio workflow | SL | HPA su CPU/RPS |
| 4 | **temporal-server** | BE | Orchestratore durevole | ST¹ | repliche fisse / Temporal Cloud |
| 5 | **worker-entity-resolution** | BE | Anti-omonimia: matching CF/P.IVA/CUP, NER | SL | KEDA su coda |
| 6 | **worker-scraping** | BE | Fetcher HTTP, robots/ToS/opt-out TDM, politeness | SL | KEDA su coda |
| 7 | **browser-pool** | BE | Chromium headless (Playwright) — memory-heavy | SL² | KEDA su coda, cap repliche |
| 8 | **worker-extraction** | BE | Estrazione testo/metadati, deduplica, filtro lingua/pertinenza | SL | KEDA su coda |
| 9 | **worker-classification** | BE | FATF dual-LLM via llm-gateway; ruolo processuale | SL | KEDA su coda (cap = quota Foundry) |
| 10 | **worker-ami-scoring** | BE | AMI; chiama SAS Viya (`score_data`) via sas-mcp-server; SHAP | SL | KEDA su coda |
| 11 | **worker-conflict-hitl** | BE | Conflict resolution, soglie, escalation | SL | KEDA su coda |
| 12 | **ingestion-connectors** | BE | Connettori PDND/ANAC/InfoCamere/OpenCoesione/BDU | SL | CronJob / KEDA |
| 13 | **llm-gateway** | BE | Gateway Azure Foundry: routing dual-LLM, rate-limit, redazione PII, cache, audit | SL | HPA su RPS |
| 14 | **sas-mcp-server** | BE | Immagine ufficiale `ghcr.io/sassoftware/sas-mcp-server` (HTTP) verso SAS Viya | SL | HPA su RPS |
| 15 | **sas-token-broker** | BE | Ottiene/rinnova token SASLogon di servizio | SL³ | 1-2 repliche |
| 16 | **postgresql (+pgvector)** | BE | Dati strutturati + vettori | ST | Azure DB for PostgreSQL |
| 17 | **neo4j** | BE | Knowledge graph (da Rilascio 3) | ST | operator / VM gestita |
| 18 | **redis** | BE | Cache, rate-limit, hash dedup | ST | Azure Cache for Redis |
| 19 | **object-store** | BE | Snapshot WARC/HTML immutabili | ST | Azure Blob (immutability policy) |
| 20 | **otel-collector** | BE | Trace/metric/log (OpenTelemetry) | SL | Deployment/DaemonSet |
| 21 | **audit-sink** | BE | Log immutabile append-only (WORM, marca temporale eIDAS) | ST | Blob WORM / ledger |

¹ Temporal richiede un datastore proprio; alternativa **Temporal Cloud**. ² memory-heavy: limiti stringenti, `PodDisruptionBudget`, node pool dedicato. ³ può essere sidecar/libreria.

> **MVP (Rilascio 1)**: `frontend`, `api`, `temporal-server`, `worker-entity-resolution`, `worker-scraping`+`browser-pool`, `worker-extraction`, Postgres, Redis, object-store, otel-collector. LLM/AMI/SAS/Neo4j nei rilasci successivi (§15).

---

## 6. Scalabilità

### 6.1 Scalare sulla coda, non solo sulla CPU
Il carico è **bursty** (arrivi a lotti per CUP/programma). Usiamo **KEDA** con trigger sulla **profondità della task queue** Temporal; ogni tipo di lavoro ha la sua coda → i pool scalano indipendentemente. L'HPA su CPU resta per i servizi sincroni (`frontend`, `api`, `llm-gateway`, `sas-mcp-server`).

### 6.2 Profili di risorsa e node pool AKS
| Profilo | Container | Node pool AKS |
|---------|-----------|---------------|
| Front-end/edge | frontend, api | `system`/`general` |
| Generale (IO-bound) | scraping, classification, ami, connectors, gateway, mcp | `general` |
| Memory-heavy | **browser-pool** | `browser` (limiti alti, cap repliche) |
| CPU-bound | entity-resolution (NER), extraction | `compute` |
| Stateful in-cluster | neo4j (gli altri store sono managed) | `data` (dischi premium) |

**Niente node pool GPU**: inferenza su Azure Foundry.

### 6.3 Backpressure
- **worker-classification**: concorrenza max vincolata dalle **quote TPM/RPM Foundry**; il `llm-gateway` fa rate-limit e coda in ingresso (evita 429 a cascata).
- **browser-pool**: cap repliche; oltre, assorbe la coda.
- **sas-mcp/Viya**: rate-limit lato gateway + circuit breaker sul worker-ami.
- **Cluster autoscaler** AKS aggiunge nodi a saturazione; `PodDisruptionBudget` protegge i lavori in volo.

### 6.4 Idempotenza
Ogni attività è idempotente (chiave = hash contenuto + versione modello): retry e repliche concorrenti non duplicano evidenze o alert.

---

## 7. Dati, stato e storage

| Store | Contenuto | Deployment (Azure) |
|-------|-----------|--------------------|
| **PostgreSQL** | Subject, Evidence, Classification, AMI, Alert | **Azure DB for PostgreSQL Flexible Server** (HA zonale, backup PITR) |
| **pgvector** | Embedding (near-duplicate/retrieval) | Estensione su Azure PostgreSQL (evita un DB vettoriale separato all'inizio) |
| **Neo4j** | Grafo alias/UBO/relazioni | Solo da Rilascio 3; operator/VM |
| **Redis** | Cache, rate-limit, hash dedup | **Azure Cache for Redis** |
| **Object store** | Snapshot WARC/HTML | **Azure Blob** con **immutability policy** (WORM) + retention |
| **Audit sink** | Disposizioni, versioni, chi/quando | Blob WORM / ledger append-only, marca temporale **eIDAS** |

Regola: gli store con stato sono **managed/operator** con backup e DR propri; le immagini applicative restano interamente stateless.

---

## 8. Networking, sicurezza e segreti

- **NetworkPolicy default-deny**; aperture esplicite: solo `worker-ami`/`worker-conflict` → `sas-mcp-server`; solo i worker LLM → `llm-gateway`; il `frontend` raggiunge **solo** l'`api`.
- **Private Endpoint** per Azure Foundry, Blob, PostgreSQL, Key Vault → il traffico resta sul **backbone Azure**, non su Internet (forte guadagno di compliance/sovranità).
- **Egress allow-list** (Azure Firewall): endpoint Foundry, `VIYA_ENDPOINT`, PDND/ANAC/InfoCamere, domini di scraping autorizzati. Tutto il resto bloccato.
- **Identità federata, non chiavi**: **AKS Workload Identity** per accesso *keyless* a Foundry (ruolo Entra "Cognitive Services OpenAI User"), Key Vault e Blob; verso SAS, service account SASLogon con token brevi (§9.3).
- **Segreti**: **Azure Key Vault** (CSI Secrets Store / External Secrets); nessun segreto in immagini o `ConfigMap`.
- **TLS ovunque**; mTLS interno opzionale (service mesh) sui percorsi con dati giudiziari.
- **Container**: non-root, filesystem read-only, `securityContext`/`seccomp`; browser-pool in sandbox con capacità minime.
- **Dati in UE** (Italy North), cloud qualificato, misure minime AgID.

---

## 9. Integrazione SAS Viya via SAS MCP server

### 9.1 Componente
Immagine ufficiale **`ghcr.io/sassoftware/sas-mcp-server`** in **HTTP mode** (`/mcp`, porta 8134), *stateless* → scalabile in orizzontale. SAS fornisce Helm chart/manifests di riferimento (ingress Contour/nginx, TLS).

### 9.2 Chi chiama chi
```
worker-ami-scoring / worker-conflict-hitl (MCP client)
        │ HTTP /mcp (in-cluster, mTLS)
        ▼
   sas-mcp-server  ── Authorization: Bearer <token SASLogon> (ALLOW_RAW_BEARER)
        │ REST + CAS
        ▼
   SAS Viya (esterna) → Model Manager · Intelligent Decisioning · CAS
```

### 9.3 Autenticazione (service-to-service)
Pattern **raw bearer** (il flusso OAuth/PKCE del MCP server è pensato per un umano con browser):
1. `sas-token-broker` si autentica a **SASLogon** con un **service account** e ottiene un access token OAuth breve.
2. Il worker chiama `sas-mcp-server` con `Authorization: Bearer <token>`; il server (`ALLOW_RAW_BEARER=true`) lo inoltra a Viya.
3. Il broker rinnova prima della scadenza; nessuna password persistita.

### 9.4 Privilegio minimo (due profili)
| Istanza | Uso | Config |
|---------|-----|--------|
| **`sas-mcp-runtime`** | Hot path: solo scoring/lettura | `MCP_TIERS=6` + `MCP_READ_ONLY=true` |
| **`sas-mcp-govops`** | Solo governance/deploy: registrazione modelli, pubblicazione decisioni | `MCP_TIERS=5,6,7`, credenziali separate |

Il runtime **non può** modificare modelli o regole: solo consumarli.

### 9.5 Cosa fa SAS Viya
- **Model Management & Scoring (Tier 6)**: registra/versiona/**monitora** il modello AMI e i modelli di supporto FATF (drift, champion/challenger, accuratezza — art. 15 AI Act); `score_data` sul campione governato.
- **Intelligent Decisioning (Tier 7)**: regole deterministiche (doppio finanziamento via CUP) e mappatura **soglia→disposizione** come ruleset/decision flow versionati e auditabili; innesto nei flussi antifrode.
- **HITL preservato**: SAS produce una **raccomandazione**; la determinazione resta all'istruttore.

### 9.6 Minimizzazione verso SAS
Verso Viya inviamo **feature derivate** (categoria FATF, severità, confidence, materialità vs CUP, ruolo, red flag), **non** il testo grezzo. Confine di compliance netto.

### 9.7 Audit
Ogni chiamata MCP registrata nell'audit sink (tool, hash input, versione modello/decisione, risposta, timestamp).

---

## 10. Integrazione LLM via Azure AI Foundry

### 10.1 llm-gateway (punto unico di governo)
Tutti i worker LLM/embedding passano dal **`llm-gateway`** (può basarsi su un proxy tipo LiteLLM): routing **dual-LLM**, rate-limit/backpressure sulle quote, **redazione PII**, logging (hash) per audit, caching semantico, cost accounting per soggetto/CUP.

### 10.2 Autenticazione
**AKS Workload Identity** verso Foundry: accesso *keyless* con ruolo Entra ("Cognitive Services OpenAI User"); nessuna API key da ruotare (§11).

### 10.3 Residenza dati e compliance (da validare in DPIA/FRIA)
- **Regione UE** (Italy North) + **Private Endpoint** verso Foundry; DPA con impegno di **non addestramento** sui nostri input.
- **Dato sensibile (art. 10 GDPR)**: l'invio di testo potenzialmente giudiziario a un servizio cloud va valutato in **DPIA/FRIA**; redazione PII + minimizzazione riducono l'esposizione. Fallback on-prem reso a basso costo dall'astrazione del gateway.
- **Egress** solo verso gli endpoint Foundry (allow-list / Private Endpoint).

---

## 11. Deployment su Azure (servizi gestiti)

Il deploy avviene sull'**account Azure esistente** (stesso tenant di Foundry), semplificando identità e rete: Foundry, storage, DB e segreti stanno nello stesso perimetro Entra, raggiungibili via Private Endpoint.

| Esigenza | Servizio Azure | Note |
|----------|----------------|------|
| Kubernetes | **AKS** | node pool multipli (§6.2), cluster autoscaler, zone di disponibilità |
| Registry immagini | **Azure Container Registry (ACR)** | scansione (Defender), firma, pull *keyless* da AKS |
| LLM/embedding | **Azure AI Foundry** | region UE, Private Endpoint, accesso keyless Entra |
| Object store | **Azure Blob Storage** | immutability policy (WORM) per WARC/audit |
| Database | **Azure DB for PostgreSQL Flexible** | estensione pgvector, HA zonale, PITR |
| Cache | **Azure Cache for Redis** | — |
| Segreti | **Azure Key Vault** | CSI Secrets Store / External Secrets |
| Identità servizi | **Entra ID + AKS Workload Identity** | federazione, **nessuna chiave statica** |
| Identità operatori | **Entra ID (OIDC/MSAL)** | SSO + RBAC; federabile con SASLogon |
| Ingress/WAF | **Application Gateway (AGIC)** o **Front Door** | TLS, WAF, routing FE/BE |
| Osservabilità | **Azure Monitor / App Insights** (via OTel) | o stack Grafana/Loki |
| Rete verso SAS Viya | **VNet peering / Private Link** (se Viya su Azure) o **VPN/ExpressRoute** (se on-prem) | mantiene il traffico privato |

**Portabilità preservata**: restano Kubernetes e Helm standard. I servizi gestiti sono adottati per ridurre l'ops ma sono **sostituibili** con equivalenti in-cluster (CloudNativePG, Redis, MinIO) senza cambiare il codice applicativo — solo la configurazione.

---

## 12. Portabilità Docker → Kubernetes

- **Parità di ambiente**: stessa immagine per dev (Docker Compose) e test/prod (AKS); cambia solo la configurazione.
- **Immagini**: multi-stage, base slim/distroless, non-root, versioni **pinnate a digest**.
- **Config 12-factor**: `ConfigMap` per la config, Key Vault per i segreti.
- **Probe** `liveness`/`readiness`/`startup`; i worker gestiscono **SIGTERM** (graceful shutdown).
- **Manifests**: **Helm** con `values` per ambiente; il chart `sas-mcp-server` di SAS come dipendenza.
- **Ambienti**: namespace `adverse-media-{dev,test,prod}`; RBAC e quote per namespace.

Percorso: **Compose in locale → Helm su AKS**, senza modifiche al codice.

---

## 13. Osservabilità e audit

- **OpenTelemetry** end-to-end: un `trace_id` segue il soggetto (scraping → estrazione → classificazione → AMI → disposizione), incluse le chiamate a `llm-gateway` e `sas-mcp-server`; export verso **Azure Monitor/App Insights** o Grafana.
- **Metriche**: profondità code, latenza per stadio, tasso 429 Foundry, tempi Viya, throughput soggetti/ora.
- **Audit immutabile** separato dai log operativi: append-only, WORM (Blob), marca temporale eIDAS; ogni disposizione con evidenze, versioni e operatore.

---

## 14. CI/CD e supply chain

- **GitHub Actions** (il repo è su GitHub) con **OIDC federato ad Azure** (nessuna credenziale cloud memorizzata) → build, push su **ACR**, deploy su **AKS** via Helm.
- **SBOM** per immagine; scansione vulnerabilità in CI con gate; **firma immagini** (cosign/notation) e verifica in admission (solo immagini firmate girano).
- Il `frontend` ha la sua pipeline (build statica, lint, test) separata dal back-end.
- Migrazioni DB come job idempotenti; promozione controllata dev→test→prod.
- `sas-mcp-server` consumato dall'immagine ufficiale **pinnata a digest** e ri-scansionata.

---

## 15. Rollout dei container per fase

| Fase | Container introdotti |
|------|----------------------|
| **Avvio** | CI/CD (GitHub Actions→ACR→AKS), ambienti; scheletro `api` e `frontend`; Postgres, Redis, Blob, otel |
| **Rilascio 1** (MVP) | `frontend` (admin-first Refine + prime viste HITL), `temporal-server`, `worker-entity-resolution`, `worker-scraping`, `browser-pool`, `worker-extraction`, `ingestion-connectors`, `audit-sink` |
| **Rilascio 2** | `llm-gateway` (Foundry), `worker-classification`, `worker-ami-scoring`, `worker-conflict-hitl`, `sas-mcp-server` (+`sas-token-broker`); UI HITL completa |
| **Rilascio 3** | `neo4j` + network analysis; hardening, drift/bias |

---

## 16. Punti aperti da confermare

1. **Scope del front-end al Rilascio 1**: sola amministrazione/configurazione, o già prime viste HITL? (cambia l'effort UI, non l'architettura)
2. **Hosting front-end**: container nginx in AKS (consigliato) vs Azure Static Web Apps.
3. **Region Azure** (Italy North) e conferma **EU Data Boundary** + DPA no-training, in DPIA/FRIA.
4. **Ammissibilità invio testo giudiziario a Foundry** (§10.3): esito DPIA; eventuale fallback on-prem.
5. **Temporal self-hosted vs Temporal Cloud**.
6. **Managed vs in-cluster** per gli store (Azure PostgreSQL/Redis/Blob vs CloudNativePG/Redis/MinIO).
7. **Connettività a SAS Viya** (Private Link/peering vs VPN/ExpressRoute) e service account SASLogon (tier/scope/rotazione).
8. **BFF sì/no** per non esporre token nel browser (§3.3).

---

## Appendice A — Compose di sviluppo (illustrativo)

> Snippet di riferimento per l'ambiente locale (non ancora materializzato nel repo). Il `frontend` è un servizio a sé, separato dal back-end.

```yaml
# docker-compose.dev.yml (bozza illustrativa)
services:
  frontend:
    build: ./frontend                       # SPA React/TS (Refine)
    ports: ["5173:80"]                       # nginx serve la build
    environment: { VITE_API_BASE: "http://localhost:8000", VITE_ENTRA_CLIENT_ID: ${ENTRA_CLIENT_ID} }

  api:
    build: ./services/api                    # FastAPI (back-end edge)
    env_file: .env
    ports: ["8000:8000"]
    depends_on: [postgres, redis, temporal]

  temporal:
    image: temporalio/auto-setup:1.25.0
    ports: ["7233:7233"]

  worker-scraping:
    build: ./services/worker-scraping
    env_file: .env
    depends_on: [temporal, redis]

  browser-pool:
    build: ./services/browser-pool           # Playwright/Chromium
    shm_size: "1gb"

  llm-gateway:
    build: ./services/llm-gateway            # verso Azure AI Foundry

  sas-mcp-server:
    image: ghcr.io/sassoftware/sas-mcp-server:<digest>
    environment:
      VIYA_ENDPOINT: ${VIYA_ENDPOINT}
      ALLOW_RAW_BEARER: "true"
      MCP_TIERS: "6"
      MCP_READ_ONLY: "true"
    ports: ["8134:8134"]

  postgres:
    image: postgres:16                        # + pgvector
    environment: { POSTGRES_PASSWORD: ${POSTGRES_PASSWORD} }
    volumes: ["pgdata:/var/lib/postgresql/data"]

  redis: { image: redis:7 }

  minio:
    image: minio/minio                        # object store S3-compatibile (WARC)
    command: server /data
    volumes: ["minio:/data"]

volumes: { pgdata: {}, minio: {} }
```

## Appendice B — Variabili d'ambiente chiave

**frontend**
| Variabile | Note |
|-----------|------|
| `VITE_API_BASE` | base URL dell'API back-end |
| `VITE_ENTRA_CLIENT_ID` / `VITE_ENTRA_AUTHORITY` | SSO Entra ID (MSAL) |

**sas-mcp-server**
| Variabile | Valore tipico | Note |
|-----------|---------------|------|
| `VIYA_ENDPOINT` | `https://viya.ente.it` | Viya esterna |
| `VIYA_AUTH` | `true` | **mai** `false` in PA |
| `ALLOW_RAW_BEARER` | `true` | pattern service-to-service |
| `MCP_TIERS` | `6` (runtime) / `5,6,7` (govops) | privilegio minimo |
| `MCP_READ_ONLY` | `true` (runtime) | 43 tool read-only |
| `MCP_LANDING_PAGE` | `false` | nessuna landing non autenticata |

**llm-gateway (Azure AI Foundry)**
| Variabile | Note |
|-----------|------|
| `AZURE_FOUNDRY_ENDPOINT` | endpoint del progetto Foundry (region UE) |
| federated identity (Workload Identity) | accesso keyless; nessuna API key statica |
| `LLM_MODEL_PRIMARY` / `LLM_MODEL_SECONDARY` | deployment dual-LLM |
| `EMBEDDING_MODEL` | modello di embedding |
| `LLM_MAX_TPM` / `LLM_MAX_RPM` | allineati alla quota Foundry (backpressure) |

---

## Appendice C — Changelog

**v1.0 → v1.1**
- **Separazione front-end / back-end** come sezione dedicata (§3): API unico confine di fiducia, il front-end non tocca dati/DB/LLM/SAS.
- **Framework front-end** (§4): React+TypeScript, admin-first con Refine → console HITL; MUI, MSAL/Entra; alternativa minima FastAPI-admin; motivazione vs Angular/Vue.
- **Deployment su Azure** (§11): cloud target fissato (account esistente), mapping ai servizi gestiti (AKS, ACR, Blob WORM, Azure PostgreSQL+pgvector, Redis, Key Vault), identità **keyless** (Entra + Workload Identity), rete con **Private Endpoint**, CI/CD GitHub Actions con OIDC.
- Diagrammi, catalogo container (aggiunto `frontend`/WAF, store→managed Azure), node pool AKS, punti aperti e rollout aggiornati di conseguenza.

---

*Documento di architettura — uso interno. I riferimenti a componenti di terze parti (SAS MCP server, Azure AI Foundry) vanno verificati sulle versioni adottate; le scelte di residenza e trattamento dati vanno validate in DPIA/FRIA con legale/DPO.*
