# Deployment e Integrazione SAS Viya — Architettura a container
## Adverse Media Screening FSC/MASE

> **Documento di architettura** · Deployment cloud-native e integrazione con SAS Viya / SAS Visual Investigator
> Versione: **1.2** · Settembre 2026 · (modifiche in [Appendice C](#appendice-c--changelog))
> Prerequisito: [documento tecnico-funzionale (baseline 1.0)](WebScraping_AdverseMedia_FSC_MASE.1.0.md)

### Decisioni di base (fissate)
- **Cloud target: Microsoft Azure** (stesso account/tenant di Foundry), orchestrazione con **AKS** → §11.
- **LLM/embedding → Microsoft Azure AI Foundry** (managed; nessun node pool GPU nel cluster).
- **SAS Viya esterna/gestita**: integrazione *via rete* attraverso **due canali** — `sas-mcp-server` (scoring/decisioning) e `svi-publisher` (popolamento SAS Visual Investigator).
- **Front-end su due console distinte**:
  - **SAS Visual Investigator (SVI)** = console **investigativa** del I livello: triage alert, dossier, **network analysis**, case management, disposizione (§3, §9.8).
  - **React + TypeScript + Vite** = console di **amministrazione, configurazione e observability** della piattaforma di web scraping (§4).
- **Network analysis su SVI** (nativa) → **Neo4j rimosso** dall'architettura.
- **Orchestratore workflow**: **Temporal** (esecuzione durevole, retry idempotenti). Alternativa leggera: Celery+Redis.

---

## Indice
1. [Obiettivi e principi](#1-obiettivi-e-principi)
2. [Vista d'insieme](#2-vista-dinsieme)
3. [Architettura del front-end (due console)](#3-architettura-del-front-end-due-console)
4. [Console di amministrazione React (framework)](#4-console-di-amministrazione-react-framework)
5. [Catalogo dei container](#5-catalogo-dei-container)
6. [Scalabilità](#6-scalabilità)
7. [Dati, stato e storage](#7-dati-stato-e-storage)
8. [Networking, sicurezza e segreti](#8-networking-sicurezza-e-segreti)
9. [Integrazione SAS Viya e SAS Visual Investigator](#9-integrazione-sas-viya-e-sas-visual-investigator)
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

- **Un servizio = un container = un processo** (12-factor): config via ambiente, segreti esterni, log su stdout, processi *stateless* dove possibile.
- **Due front-end per due popolazioni**: gli **investigatori** (I livello) lavorano in **SVI**; gli **amministratori/ops** della piattaforma nella console React. Nessuno dei due accede direttamente ai dati interni: solo tramite interfacce governate (§3).
- **Disaccoppiamento via coda**: ingestion e agenti scalano indipendentemente; la profondità della coda è il segnale di autoscaling primario.
- **Isolamento per profilo di risorsa**: browser headless e inferenza hanno deployment/node pool dedicati.
- **Portabilità prima del lock-in**: Kubernetes + Helm standard; i servizi gestiti Azure (§11) riducono l'ops ma restano **sostituibili**.
- **Sicurezza e sovranità del dato (PA)**: default-deny di rete, traffico su **Private Endpoint**, **identità federata** al posto di chiavi statiche, dati in UE.
- **Minimizzazione differenziata verso l'esterno** (§9.9): testo grezzo → solo Foundry (con redazione); feature derivate → MCP scoring; dossier/entità/alert → SVI (dentro il perimetro governato SAS).

---

## 2. Vista d'insieme

```
   Amministratori/Ops (browser)        Investigatori I livello (browser)      Fonti web · Azure Foundry · SAS Viya · PDND
            │ Entra ID                          │ SASLogon/Entra                        ▲ (Private Endpoint / egress allow-list)
╔═══════════╪═══════════════════════════════════╪═══════════════════════════════════════╪══════════════════════════════════════╗
║  AZURE · AKS · adverse-media-{env} · UE        │                                       │                                      ║
║  ┌────────┴───────────┐              ┌─────────┴──────────────┐                        │                                      ║
║  │ admin-console       │              │  SAS Visual Investigator│  (parte di SAS Viya, ESTERNA)                              ║
║  │ (React/TS · nginx)  │              │  triage · dossier ·     │  ◀── network analysis · case mgmt · disposizione           ║
║  │ config/observability│              │  NETWORK ANALYSIS       │                        │                                      ║
║  └────────┬───────────┘              └─────────▲──────────────┘                        │                                      ║
║           │ REST + JWT                         │ Data Hub + Alerts API                  │                                      ║
║  ┌────────┴───────────────────────── BACK-END TIER ───────────────────────────────────┴──────────┐                          ║
║  │ api (FastAPI: authz/RBAC/audit) · TEMPORAL (server + task queues)                                │                          ║
║  │ worker: entity-res · scraping/browser · extraction · classification · ami · conflict-resolution  │                          ║
║  │ llm-gateway ─▶ Azure Foundry    sas-mcp-server ─▶ Viya(score/decide)    svi-publisher ─▶ SVI      │                          ║
║  │ ingestion-connectors ─▶ PDND                                                                      │                          ║
║  └────────┬─────────────────────────────────────────────────────────────────────────────────────────┘                          ║
║  ┌────────┴──── STATO (servizi gestiti Azure, §11) ────────────────────────────────────┐                                      ║
║  │ Azure DB for PostgreSQL(+pgvector) · Azure Cache for Redis · Blob Storage (WORM)      │   (Neo4j RIMOSSO: grafo su SVI)      ║
║  └───────────────────────────────────────────────────────────────────────────────────┘                                      ║
║  Identità: Entra ID + AKS Workload Identity     Segreti: Key Vault                                                            ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## 3. Architettura del front-end (due console)

### 3.1 Ripartizione delle responsabilità
| Console | Utenti | Cosa fa | Dove gira |
|---------|--------|---------|-----------|
| **SAS Visual Investigator** | Investigatori I livello, case manager | Triage e disposizione alert, dossier/evidenze, **network analysis** (node-link, centralità, community), case management, Viya Copilot | SAS Viya (esterna) |
| **admin-console (React)** | Team di piattaforma, amministratori, auditor tecnici | Configurazione scraping (registro fonti, robots/ToS/opt-out, politeness), scheduling e run-control, parametri Entity Resolution, soglie/versioni modello e prompt, stato connettori, **observability** del sistema, audit tecnico | AKS (nostra) |

**Confine netto**: l'attività *investigativa* sul singolo soggetto/alert (incluso il grafo) è **tutta in SVI**; la console React **non** mostra dossier né grafi investigativi — governa la *piattaforma*, non i casi.

### 3.2 Perché il grafo sta in SVI (e Neo4j esce)
SVI fornisce nativamente network viewer, link expansion e metriche di centralità (closeness/betweenness/influence) e community detection. Duplicarlo con un Neo4j + UI custom violerebbe il principio "**sinergia, non duplicazione**" del capitolato. La nostra pipeline **calcola** relazioni (UBO, CUP, co-occorrenze) e le **pubblica in SVI**, che le visualizza e le fa esplorare all'investigatore.

### 3.3 Il confine di fiducia resta l'interfaccia governata
- **Verso la console React**: unico ingresso è l'**API FastAPI**, che autentica (JWT Entra ID), autorizza (RBAC), valida e scrive l'audit. La SPA non tocca DB/coda/LLM/SAS.
- **Verso SVI**: i dati arrivano **solo** tramite il `svi-publisher` (API SVI, §9.8), non da accessi diretti dell'app al DB. SVI applica i propri controlli d'accesso e la propria auditabilità.
- **Autenticazione operatori**: SVI via SASLogon (federabile con **Entra ID** per SSO unico); console React via Entra ID/MSAL. Servizi → Workload Identity federata (§8).

---

## 4. Console di amministrazione React (framework)

### 4.1 Scope (ristretto e chiaro)
La console React copre **amministrazione, configurazione e observability della piattaforma di web scraping** — **non** l'investigazione (che è in SVI). In pratica:
- **Configurazione**: registro fonti (credibilità, `robots.txt`/ToS/opt-out TDM, politeness/crawl-delay per dominio), scheduling e run-control dello scraping (avvia/sospendi), parametri Entity Resolution, soglie AMI e versioni modello/prompt, credenziali/stato dei connettori (PDND/ANAC/InfoCamere).
- **Observability**: salute del sistema, profondità code, throughput per fonte, tassi di errore, uso/costo Foundry, latenza chiamate SAS, drift/bias.
- **Audit tecnico** della piattaforma (distinto dall'audit *investigativo* dei casi, che vive in SVI).

> Nota: le **regole di disposizione governate** (soglia→disposizione, red flag) vivono in **SAS Intelligent Decisioning** (§9.6), non nella console React. La console configura i *parametri di piattaforma*, non le decisioni governate SAS: nessuna sovrapposizione.

### 4.2 Stack raccomandato
| Livello | Scelta | Perché |
|---------|--------|--------|
| Base | **React + TypeScript + Vite** | Ampio bacino di competenze (handover/formazione PA), ottimo supporto Entra/MSAL |
| Acceleratore admin | **Refine** (refine.dev) | Auth provider (MSAL/Entra), **RBAC**, data provider REST/OpenAPI, CRUD scaffolding → console di config rapida |
| UI | **MUI + MUI X (DataGrid)** | Maturo, accessibile (WCAG/AGID/L.4/2004) |
| Dati/form | **TanStack Query** · React Hook Form + Zod | Fetch/caching robusti, validazione tipizzata |
| Observability | **Pannelli Grafana embeddati** / Azure Monitor workbook + poche viste React di dominio | Riuso dello stack metriche invece di ricostruire grafici (§13) |

Non servono più librerie di grafo (Cytoscape/force-graph) lato React: la network analysis è in SVI.

### 4.3 Alternativa minima
Se la console dovesse restare *solo* CRUD di configurazione, si potrebbe usare un admin **nativo FastAPI** (Starlette-Admin/SQLAdmin) senza build front-end. Ma per l'**observability** e una UX ops decente, la SPA React è la scelta target.

---

## 5. Catalogo dei container

Legenda: **FE** front-end · **BE** back-end · **SL** stateless · **ST** stateful (managed/operator).

| # | Container | Tier | Ruolo | Tipo | Autoscaling |
|---|-----------|------|-------|------|-------------|
| 1 | **admin-console** | FE | SPA React (config/observability piattaforma) servita da nginx | SL | HPA / CDN |
| 2 | **ingress/WAF** | — | Application Gateway o Front Door (TLS, WAF, routing) | — | gestito |
| 3 | **api** | BE | FastAPI: authz/RBAC, validazione, audit, API per la console, avvio workflow | SL | HPA su CPU/RPS |
| 4 | **temporal-server** | BE | Orchestratore durevole | ST¹ | repliche fisse / Temporal Cloud |
| 5 | **worker-entity-resolution** | BE | Anti-omonimia: matching CF/P.IVA/CUP, NER | SL | KEDA su coda |
| 6 | **worker-scraping** | BE | Fetcher HTTP, robots/ToS/opt-out TDM, politeness | SL | KEDA su coda |
| 7 | **browser-pool** | BE | Chromium headless (Playwright) — memory-heavy | SL² | KEDA su coda, cap repliche |
| 8 | **worker-extraction** | BE | Estrazione testo/metadati, deduplica, filtro lingua/pertinenza | SL | KEDA su coda |
| 9 | **worker-classification** | BE | FATF dual-LLM via llm-gateway; ruolo processuale | SL | KEDA su coda (cap = quota Foundry) |
| 10 | **worker-ami-scoring** | BE | AMI; chiama Viya (`score_data`) via sas-mcp-server; SHAP | SL | KEDA su coda |
| 11 | **worker-conflict-resolution** | BE | Conflict resolution, soglie; innesca la pubblicazione dell'alert su SVI | SL | KEDA su coda |
| 12 | **ingestion-connectors** | BE | Connettori PDND/ANAC/InfoCamere/OpenCoesione/BDU | SL | CronJob / KEDA |
| 13 | **llm-gateway** | BE | Gateway Azure Foundry: routing dual-LLM, rate-limit, redazione PII, cache, audit | SL | HPA su RPS |
| 14 | **sas-mcp-server** | BE | Immagine ufficiale `ghcr.io/sassoftware/sas-mcp-server` (HTTP): scoring/decisioning | SL | HPA su RPS |
| 15 | **sas-token-broker** | BE | Ottiene/rinnova token SASLogon di servizio | SL³ | 1-2 repliche |
| 16 | **svi-publisher** | BE | Pubblica entità/relazioni/evidenze/alert in **SVI** (Data Hub + Alerts REST) | SL | KEDA su coda |
| 17 | **postgresql (+pgvector)** | BE | Dati strutturati + vettori | ST | Azure DB for PostgreSQL |
| 18 | **redis** | BE | Cache, rate-limit, hash dedup | ST | Azure Cache for Redis |
| 19 | **object-store** | BE | Snapshot WARC/HTML immutabili | ST | Azure Blob (immutability/WORM) |
| 20 | **otel-collector** | BE | Trace/metric/log (OpenTelemetry) | SL | Deployment/DaemonSet |
| 21 | **audit-sink** | BE | Log immutabile append-only (WORM, marca temporale eIDAS) | ST | Blob WORM / ledger |

¹ Temporal richiede un datastore proprio; alternativa **Temporal Cloud**. ² memory-heavy: limiti stringenti, `PodDisruptionBudget`, node pool dedicato. ³ può essere sidecar/libreria.
**Rimosso rispetto alla v1.1**: `neo4j` (la network analysis è nativa in SVI).

> **MVP (Rilascio 1)**: `admin-console`, `api`, `temporal-server`, `worker-entity-resolution`, `worker-scraping`+`browser-pool`, `worker-extraction`, Postgres, Redis, object-store, otel-collector. LLM/AMI/SAS/SVI nei rilasci successivi (§15).

---

## 6. Scalabilità

### 6.1 Scalare sulla coda
Carico **bursty** (lotti per CUP/programma) → **KEDA** sulla profondità delle task queue Temporal; ogni tipo di lavoro ha la sua coda. HPA su CPU per i servizi sincroni (`admin-console`, `api`, `llm-gateway`, `sas-mcp-server`, `svi-publisher`).

### 6.2 Profili di risorsa e node pool AKS
| Profilo | Container | Node pool |
|---------|-----------|-----------|
| Front-end/edge | admin-console, api | `system`/`general` |
| Generale (IO-bound) | scraping, classification, ami, connectors, gateway, mcp, svi-publisher | `general` |
| Memory-heavy | **browser-pool** | `browser` (limiti alti, cap repliche) |
| CPU-bound | entity-resolution (NER), extraction | `compute` |

Gli store con stato sono **managed** (Azure) → nessun node pool `data` in-cluster. **Niente GPU**: inferenza su Foundry.

### 6.3 Backpressure
- **worker-classification**: concorrenza max = quote **TPM/RPM Foundry**; `llm-gateway` fa rate-limit/coda (evita 429 a cascata).
- **browser-pool**: cap repliche; oltre, assorbe la coda.
- **sas-mcp/svi/Viya**: rate-limit lato gateway/publisher + circuit breaker.
- **Cluster autoscaler** AKS; `PodDisruptionBudget` protegge i lavori in volo.

### 6.4 Idempotenza
Ogni attività idempotente (chiave = hash contenuto + versione modello): retry e repliche non duplicano evidenze, alert o pubblicazioni SVI.

---

## 7. Dati, stato e storage

| Store | Contenuto | Deployment (Azure) |
|-------|-----------|--------------------|
| **PostgreSQL** | Subject, Evidence, Classification, AMI, Alert (sistema di record) | **Azure DB for PostgreSQL Flexible** (HA zonale, PITR) |
| **pgvector** | Embedding (near-duplicate/retrieval) | Estensione su Azure PostgreSQL |
| **Redis** | Cache, rate-limit, hash dedup | **Azure Cache for Redis** |
| **Object store** | Snapshot WARC/HTML | **Azure Blob** con immutability policy (WORM) + retention |
| **Audit sink** | Disposizioni, versioni, chi/quando | Blob WORM / ledger append-only, marca temporale **eIDAS** |

Il **grafo** (alias/UBO/relazioni) non è più uno store nostro: è materializzato in **SVI**. Postgres resta il **sistema di record**; SVI può leggere i dati come **sorgente esterna read-only** (Data Hub) oppure riceverli caricati (§9.8).

---

## 8. Networking, sicurezza e segreti

- **NetworkPolicy default-deny**; aperture esplicite: solo `worker-ami`/`worker-conflict` → `sas-mcp-server`; solo `svi-publisher` → API SVI/Viya; solo i worker LLM → `llm-gateway`; la `admin-console` raggiunge **solo** l'`api`.
- **Private Endpoint** per Azure Foundry, Blob, PostgreSQL, Key Vault → traffico sul backbone Azure, non su Internet.
- **Egress allow-list** (Azure Firewall): Foundry, `VIYA_ENDPOINT`/SVI, PDND/ANAC/InfoCamere, domini di scraping autorizzati.
- **Identità federata, non chiavi**: **AKS Workload Identity** per Foundry (ruolo Entra "Cognitive Services OpenAI User"), Key Vault, Blob; verso SAS/SVI, service account SASLogon con token brevi (§9.3).
- **Segreti**: **Azure Key Vault** (CSI / External Secrets); nessun segreto in immagini o `ConfigMap`.
- **TLS ovunque**; mTLS interno opzionale sui percorsi con dati giudiziari.
- **Container** non-root, filesystem read-only, `securityContext`/`seccomp`; browser-pool in sandbox.
- **Dati in UE** (Italy North), cloud qualificato, misure minime AgID.

---

## 9. Integrazione SAS Viya e SAS Visual Investigator

Due canali complementari verso lo stesso ambiente SAS Viya esterno.

### 9.1 Componenti
- **`sas-mcp-server`** — immagine ufficiale in **HTTP mode** (`/mcp`, 8134), *stateless*: **scoring e decisioning** (compute governato).
- **`svi-publisher`** — nostro servizio: popola **SAS Visual Investigator** via **Data Hub API** (entità/relazioni) e **Alerts API** (alert), usando le REST API SAS Viya/SVI. Le operazioni SVI non rientrano nei 9 tier del MCP server, quindi hanno un canale dedicato.

### 9.2 Chi chiama chi
```
worker-ami / worker-conflict  ──▶ sas-mcp-server ──▶ Viya:  score_data (AMI), decision flow (disposizione)
worker-conflict ──▶ svi-publisher ──▶ SVI:  Data Hub (entità/relazioni/evidenze) + Alerts (crea alert in coda I livello)
Investigatore I livello  ──▶  SVI  (triage · network analysis · case · disposizione)  ──▶ feedback ──▶ pipeline
```

### 9.3 Autenticazione (service-to-service)
`sas-token-broker` ottiene un token OAuth **SASLogon** con un **service account**; `sas-mcp-server` lo usa via `ALLOW_RAW_BEARER=true`, `svi-publisher` lo usa come Bearer sulle REST SVI. Token brevi, rinnovo automatico, nessuna password persistita.

### 9.4 Privilegio minimo (MCP, due profili)
| Istanza | Uso | Config |
|---------|-----|--------|
| **`sas-mcp-runtime`** | Hot path: solo scoring/lettura | `MCP_TIERS=6` + `MCP_READ_ONLY=true` |
| **`sas-mcp-govops`** | Governance/deploy: registrazione modelli, pubblicazione decisioni | `MCP_TIERS=5,6,7`, credenziali separate |

Il `svi-publisher` usa un service account SVI con permessi limitati alle entity type e alle code di competenza.

### 9.5 Model Management & Scoring (Tier 6)
Viya registra/versiona/**monitora** il modello AMI e i modelli di supporto FATF (drift, champion/challenger, accuratezza — art. 15 AI Act); `score_data` sul campione governato.

### 9.6 Intelligent Decisioning (Tier 7)
Regole deterministiche (doppio finanziamento via CUP) e mappatura **soglia→disposizione** come ruleset/decision flow versionati e auditabili; innesto nei flussi antifrode. Producono una **raccomandazione**; la determinazione resta all'istruttore in SVI.

### 9.7 (spostato) — vedi 9.5/9.6

### 9.8 SAS Visual Investigator — modello dati e alert
- **Modello dati (Data Hub)**: definiamo entity type coerenti col capitolato — *Subject, UBO, Impresa, Intervento/CUP, Evidence* — e relazioni (UBO-di, esecutore-di, collegato-a-CUP, co-occorrenza). Due opzioni di alimentazione:
  1. **Federazione**: Postgres esposto come **sorgente esterna read-only** mappata nel modello SVI (nessuna duplicazione; Postgres resta sistema di record). *Preferibile* se la latenza e i connettori lo consentono.
  2. **Caricamento**: dati promossi in **CAS** e caricati nel modello SVI (maggiore controllo, ma duplica il dato).
- **Alert (Alerts API)**: al superamento delle soglie, `svi-publisher` crea in SVI l'alert con AMI, driver, materialità (CUP), riferimenti alle evidenze; SVI lo instrada alla **coda del I livello**.
- **Investigazione**: l'analista in SVI fa triage, apre il **network viewer**, esplora relazioni/centralità, consulta il dossier, usa Viya Copilot per sintesi NL, e **dispone** (chiude/escala) gestendo il caso.
- **Feedback loop**: la disposizione e le annotazioni tornano alla pipeline (via API/eventi SVI) per la ricalibrazione di regole e modelli (continuous learning del capitolato).

### 9.9 Minimizzazione differenziata dei dati
| Destinazione | Cosa esce | Nota |
|--------------|-----------|------|
| **Azure Foundry** | Testo articolo per classificazione/embedding | Esterno (provider USA): **punto DPIA**; redazione PII + minimizzazione |
| **SAS MCP (scoring/decisioning)** | Solo **feature derivate** | Nessun testo grezzo |
| **SVI (Data Hub/Alerts)** | Entità, relazioni, **evidenze/dossier**, AMI, alert | Più ricco, ma **dentro il perimetro governato SAS** (ente) |

### 9.10 Audit
Ogni chiamata MCP e ogni pubblicazione SVI è registrata nell'audit sink (operazione, hash input, versione modello/decisione, id alert/caso, timestamp).

### 9.11 Confini di servizio: perché `sas-mcp-server` e `svi-publisher` sono microservizi dedicati
Sì, è la scelta corretta ed è già quella adottata (container #14 e #16). Motivazioni:

- **Adapter / Anti-Corruption Layer**: `svi-publisher` incapsula *tutta* la conoscenza specifica di SVI (mapping del data model, Data Hub/Alerts API, quirk di versione). Se l'API SVI cambia, cambia **solo** questo servizio; il core della pipeline resta disaccoppiato. Analogamente `sas-mcp-server` è il gateway governato verso Viya per scoring/decisioning.
- **Componente di terze parti**: `sas-mcp-server` è l'**immagine ufficiale SAS** — si esegue *as-is*, pinnata a digest, aggiornata/scansionata per conto suo; non si incorpora nel nostro processo. Un container dedicato è l'unico modo sensato.
- **Isolamento di sicurezza (blast radius)**: sono gli unici due servizi con **egress verso Viya/SVI**; isolarli rende netta la NetworkPolicy (solo `worker-ami`/`worker-conflict` → mcp; solo `worker-conflict` → publisher) e lo scoping delle credenziali (service account dedicati, token brevi). Il MCP gira a **privilegio minimo** con i due profili (§9.4).
- **Scaling indipendente**: entrambi *stateless* → scalano sul proprio carico (RPS per l'MCP, profondità coda per il publisher), separati dai worker CPU/memory-bound.
- **Resilienza**: `svi-publisher` è **guidato da coda con pattern *outbox*** — se SVI è lento o indisponibile, gli alert restano in coda e vengono ripubblicati in modo **idempotente**, senza bloccare la pipeline. L'`sas-mcp-server` è invocato in modo **sincrono dentro un'*activity* Temporal**, con timeout/retry/circuit breaker localizzati all'activity.
- **Riuso e testabilità**: più worker condividono un unico gateway governato invece di incorporare un client ciascuno; l'integrazione SAS/SVI (competenza specialistica) diventa testabile in isolamento (mock) e assegnabile a chi ha lo skill SAS.

**Raffinamenti**
- **`sas-token-broker` come *sidecar*** (non servizio centrale): il token SASLogon viene coniato accanto al consumatore (mcp/publisher), evitando che i token attraversino la rete verso un broker condiviso — meno superficie, un hop in meno.
- **No nanoservizi**: `svi-publisher` è un **singolo bounded context** (tutto l'I/O verso SVI), da non spezzare ulteriormente; l'obiettivo è un confine di integrazione pulito, non la frammentazione.

---

## 10. Integrazione LLM via Azure AI Foundry

### 10.1 llm-gateway (punto unico di governo)
Tutti i worker LLM/embedding passano dal **`llm-gateway`** (può basarsi su LiteLLM): routing **dual-LLM**, rate-limit/backpressure sulle quote, **redazione PII**, logging (hash) per audit, caching semantico, cost accounting per soggetto/CUP.

### 10.2 Autenticazione
**AKS Workload Identity** verso Foundry: accesso *keyless* (ruolo Entra), nessuna API key statica.

### 10.3 Residenza dati e compliance (da validare in DPIA/FRIA)
- **Regione UE** (Italy North) + **Private Endpoint**; DPA con **non addestramento** sugli input.
- **Dato sensibile (art. 10 GDPR)**: l'invio di testo potenzialmente giudiziario a Foundry va valutato in **DPIA/FRIA**; redazione PII + minimizzazione riducono l'esposizione; fallback on-prem reso a basso costo dall'astrazione del gateway.

---

## 11. Deployment su Azure (servizi gestiti)

Deploy sull'**account Azure esistente** (stesso tenant di Foundry): identità e rete semplificate (stesso perimetro Entra, Private Endpoint).

| Esigenza | Servizio Azure | Note |
|----------|----------------|------|
| Kubernetes | **AKS** | node pool multipli (§6.2), autoscaler, zone |
| Registry | **ACR** | scansione, firma, pull keyless da AKS |
| LLM/embedding | **Azure AI Foundry** | region UE, Private Endpoint, keyless Entra |
| Object store | **Azure Blob** | immutability/WORM per WARC/audit |
| Database | **Azure DB for PostgreSQL Flexible** | pgvector, HA zonale, PITR |
| Cache | **Azure Cache for Redis** | — |
| Segreti | **Azure Key Vault** | CSI / External Secrets |
| Identità servizi | **Entra ID + AKS Workload Identity** | nessuna chiave statica |
| Identità utenti | **Entra ID (OIDC/MSAL)** | console React; SVI via SASLogon federabile con Entra |
| Ingress/WAF | **Application Gateway (AGIC)** o **Front Door** | TLS, WAF |
| Osservabilità | **Azure Monitor / App Insights** (via OTel) | o Grafana/Loki |
| Rete verso SAS Viya/SVI | **Private Link/peering** (se Viya su Azure) o **VPN/ExpressRoute** (on-prem) | traffico privato |

**Portabilità preservata**: Kubernetes/Helm standard; i servizi gestiti sono **sostituibili** (CloudNativePG/Redis/MinIO) senza cambiare il codice.

---

## 12. Portabilità Docker → Kubernetes

- **Parità di ambiente**: stessa immagine dev (Compose) e test/prod (AKS); cambia solo la config.
- **Immagini** multi-stage, slim/distroless, non-root, **pinnate a digest**.
- **Config 12-factor**; `ConfigMap` + Key Vault.
- **Probe** liveness/readiness/startup; **SIGTERM** per graceful shutdown dei worker.
- **Manifests Helm** con `values` per ambiente; chart `sas-mcp-server` come dipendenza.
- **Namespace** `adverse-media-{dev,test,prod}`; RBAC e quote.

Percorso: **Compose in locale → Helm su AKS**, senza modifiche al codice.

---

## 13. Osservabilità e audit

- **OpenTelemetry** end-to-end: un `trace_id` segue il soggetto (scraping → estrazione → classificazione → AMI → disposizione), incluse le chiamate a `llm-gateway`, `sas-mcp-server` e `svi-publisher`; export verso **Azure Monitor/App Insights** o Grafana.
- La **console React** consuma queste metriche per l'observability di piattaforma (pannelli embeddati + viste di dominio: salute fonti, politeness/robots per dominio, code, costi Foundry).
- **Audit immutabile** separato dai log operativi: append-only, WORM (Blob), marca temporale eIDAS. L'audit *investigativo* dei casi vive in **SVI**; i due audit sono correlati per `alert_id`/`case_id`.

---

## 14. CI/CD e supply chain

- **GitHub Actions** con **OIDC federato ad Azure** (nessuna credenziale cloud memorizzata) → build, push su **ACR**, deploy su **AKS** via Helm.
- **SBOM** per immagine; scansione vulnerabilità con gate; **firma immagini** (cosign/notation) e verifica in admission.
- `admin-console` ha pipeline propria (build statica, lint, test) separata dal back-end.
- Migrazioni DB idempotenti; promozione dev→test→prod.
- `sas-mcp-server` dall'immagine ufficiale **pinnata a digest** e ri-scansionata.

---

## 15. Rollout dei container per fase

| Fase | Container introdotti |
|------|----------------------|
| **Avvio** | CI/CD (GitHub Actions→ACR→AKS), ambienti; scheletro `api` e `admin-console`; Postgres, Redis, Blob, otel |
| **Rilascio 1** (MVP) | `admin-console` (config/observability), `temporal-server`, `worker-entity-resolution`, `worker-scraping`, `browser-pool`, `worker-extraction`, `ingestion-connectors`, `audit-sink` |
| **Rilascio 2** | `llm-gateway` (Foundry), `worker-classification`, `worker-ami-scoring`, `worker-conflict-resolution`, `sas-mcp-server` (+`sas-token-broker`), **`svi-publisher`** → alert e **network analysis in SVI** |
| **Rilascio 3** | Pipeline OCR/NER da PDF; hardening, monitoraggio drift/bias, tuning soglie |

La network analysis non è più un lavoro Rilascio 3 con Neo4j: è **nativa in SVI** e arriva col `svi-publisher` in Rilascio 2.

---

## 16. Punti aperti da confermare

1. **Alimentazione SVI**: federazione di Postgres come sorgente esterna read-only (preferita) **vs** caricamento in CAS (§9.8); conferma versione/API SVI (Data Hub/Alerts).
2. **Generazione alert**: solo via `svi-publisher` (Alerts API) **o** anche scenari nativi SVI su dati federati.
3. **SSO**: federazione **SASLogon ↔ Entra ID** per identità unica investigatori/admin.
4. **Region Azure** (Italy North) + **EU Data Boundary** + DPA no-training (DPIA/FRIA).
5. **Ammissibilità invio testo giudiziario a Foundry** (§10.3): esito DPIA; eventuale fallback on-prem.
6. **Temporal** self-hosted vs Temporal Cloud.
7. **Connettività a SAS Viya/SVI** (Private Link/peering vs VPN/ExpressRoute) e service account (scope/rotazione).
8. **Scope console React al Rilascio 1**: config essenziale + prime viste observability.

---

## Appendice A — Compose di sviluppo (illustrativo)

> Snippet di riferimento per l'ambiente locale (non ancora materializzato nel repo). `admin-console` e back-end sono separati; SVI è esterno (non si emula in locale: si usa un ambiente Viya di test).

```yaml
# docker-compose.dev.yml (bozza illustrativa)
services:
  admin-console:
    build: ./admin-console                   # SPA React/TS (Refine) — config/observability
    ports: ["5173:80"]
    environment: { VITE_API_BASE: "http://localhost:8000", VITE_ENTRA_CLIENT_ID: ${ENTRA_CLIENT_ID} }

  api:
    build: ./services/api                     # FastAPI (back-end edge)
    env_file: .env
    ports: ["8000:8000"]
    depends_on: [postgres, redis, temporal]

  temporal: { image: temporalio/auto-setup:1.25.0, ports: ["7233:7233"] }

  worker-scraping:
    build: ./services/worker-scraping
    env_file: .env
    depends_on: [temporal, redis]

  browser-pool:
    build: ./services/browser-pool            # Playwright/Chromium
    shm_size: "1gb"

  llm-gateway:
    build: ./services/llm-gateway             # verso Azure AI Foundry

  sas-mcp-server:
    image: ghcr.io/sassoftware/sas-mcp-server:<digest>
    environment: { VIYA_ENDPOINT: ${VIYA_ENDPOINT}, ALLOW_RAW_BEARER: "true", MCP_TIERS: "6", MCP_READ_ONLY: "true" }
    ports: ["8134:8134"]

  svi-publisher:
    build: ./services/svi-publisher           # Data Hub + Alerts REST verso SVI
    env_file: .env
    environment: { VIYA_ENDPOINT: ${VIYA_ENDPOINT} }

  postgres:
    image: postgres:16                         # + pgvector
    environment: { POSTGRES_PASSWORD: ${POSTGRES_PASSWORD} }
    volumes: ["pgdata:/var/lib/postgresql/data"]

  redis: { image: redis:7 }

  minio:
    image: minio/minio                         # object store (WARC)
    command: server /data
    volumes: ["minio:/data"]

volumes: { pgdata: {}, minio: {} }
```

## Appendice B — Variabili d'ambiente chiave

**admin-console**: `VITE_API_BASE`, `VITE_ENTRA_CLIENT_ID`/`VITE_ENTRA_AUTHORITY` (SSO Entra ID/MSAL).

**sas-mcp-server**
| Variabile | Valore tipico | Note |
|-----------|---------------|------|
| `VIYA_ENDPOINT` | `https://viya.ente.it` | Viya esterna |
| `VIYA_AUTH` | `true` | **mai** `false` in PA |
| `ALLOW_RAW_BEARER` | `true` | pattern service-to-service |
| `MCP_TIERS` | `6` (runtime) / `5,6,7` (govops) | privilegio minimo |
| `MCP_READ_ONLY` | `true` (runtime) | 43 tool read-only |
| `MCP_LANDING_PAGE` | `false` | nessuna landing non autenticata |

**svi-publisher**: `VIYA_ENDPOINT`, `SVI_DATAHUB_BASE`, `SVI_ALERTS_BASE`, service account SASLogon (via broker).

**llm-gateway (Azure AI Foundry)**: `AZURE_FOUNDRY_ENDPOINT` (region UE), Workload Identity (keyless), `LLM_MODEL_PRIMARY`/`LLM_MODEL_SECONDARY`, `EMBEDDING_MODEL`, `LLM_MAX_TPM`/`LLM_MAX_RPM`.

---

## Appendice C — Changelog

**v1.1 → v1.2**
- **Front-end ridefinito su due console**: **SAS Visual Investigator** per l'investigazione del I livello (triage, dossier, **network analysis**, case management, disposizione) e **console React** per amministrazione/configurazione/**observability** della piattaforma di scraping (§3, §4).
- **Neo4j rimosso**: la network analysis è nativa in SVI (§3.2, §5, §7).
- **Nuovo canale d'integrazione `svi-publisher`** verso SVI (Data Hub + Alerts API), distinto dal `sas-mcp-server` (scoring/decisioning); modello dati SVI, generazione alert, feedback loop (§9.8).
- **Minimizzazione differenziata** dei dati per destinazione (Foundry vs MCP vs SVI) (§9.9).
- Catalogo container, node pool, rollout (network analysis in Rilascio 2 via SVI) e punti aperti aggiornati.

**v1.0 → v1.1**
- Separazione front-end/back-end; framework front-end React; deploy Azure (AKS/ACR/Blob/PostgreSQL/Key Vault), identità keyless, Private Endpoint, CI/CD GitHub Actions.

---

*Documento di architettura — uso interno. I riferimenti a componenti di terze parti (SAS MCP server, SAS Visual Investigator, Azure AI Foundry) vanno verificati sulle versioni adottate; le scelte di residenza e trattamento dati vanno validate in DPIA/FRIA con legale/DPO.*
