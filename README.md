# Adverse Media Screening — FSC / Pilota MASE

Applicazione di **web scraping e analisi multi-agente per l'adverse media screening** dei beneficiari, soggetti attuatori e imprese esecutrici degli interventi finanziati dal **Fondo per lo Sviluppo e la Coesione (FSC)** di competenza del **MASE**, a supporto dei controlli desk di I livello (Si.Ge.Co. / SIM).

Lo strumento è un **ausilio istruttorio** (decision-support) *explainable* e auditabile: individua e ordina per priorità le verifiche, ma **non decide** — la determinazione resta all'istruttore, senza scoring automatico (conforme a GDPR e AI Act).

## Documentazione

| Documento | Contenuto |
|-----------|-----------|
| [`docs/WebScraping_AdverseMedia_FSC_MASE.1.0.md`](docs/WebScraping_AdverseMedia_FSC_MASE.1.0.md) | Documento tecnico-funzionale **(baseline 1.0)**: architettura, modulo di scraping, fonti, modello dati, governance, piano di sviluppo — allineato alle decisioni su SVI, React admin, Azure/Foundry e integrazione SAS |
| [`docs/NOTE_DI_REVISIONE.md`](docs/NOTE_DI_REVISIONE.md) | Memo di revisione esperta: rilievi ordinati per criticità, razionale e punti aperti |
| [`docs/DEPLOYMENT_E_INTEGRAZIONE_SAS.md`](docs/DEPLOYMENT_E_INTEGRAZIONE_SAS.md) | Architettura di deployment a container su **due ambienti** (locale su Docker Desktop → produzione Azure/AKS); due console (SAS Visual Investigator per l'investigazione, React per admin/config/observability); integrazione SAS Viya via SAS MCP server (scoring/decisioning) e `svi-publisher` (Data Hub/Alerts); LLM via Azure AI Foundry (anche in locale) |
| [`docs/SVILUPPO_LOCALE.md`](docs/SVILUPPO_LOCALE.md) | Guida allo sviluppo locale su Docker Desktop: prerequisiti, avvio, LLM su Foundry in locale, mock SAS/SVI, struttura del repo |

## Pilastri di progetto

- **Compliant by design** — base giuridica art. 10 GDPR per i dati giudiziari, DPIA + FRIA (art. 27 AI Act), HITL, audit trail immutabile.
- **Anti-omonimia** — Entity Resolution obbligatoria (matching deterministico su CF/P.IVA/CUP) prima di qualsiasi giudizio.
- **Materialità** — ogni alert è ancorato allo specifico intervento (**CUP/CIG**) e al ruolo del soggetto.
- **Fonti sostenibili** — feed licenziati come spina dorsale, scraping conforme (robots.txt / ToS / opt-out TDM) sulle fonti pubbliche istituzionali.
- **Sinergia, non duplicazione** — complementare ad ARACHNE/PIAF; aggiunge il segnale "notizie negative".

## Avvio rapido (sviluppo locale)

Ambiente locale su **Docker Desktop** (guida completa: [`docs/SVILUPPO_LOCALE.md`](docs/SVILUPPO_LOCALE.md)):
```bash
cp .env.example .env    # valorizzare AZURE_FOUNDRY_ENDPOINT, LLM_MODEL_*, e il service principal dev
docker compose -f docker-compose.dev.yml up --build     # oppure: make up
```
Console admin su http://localhost:5173 · API su http://localhost:8000/docs · Temporal UI su http://localhost:8233.

> L'LLM è su **Azure AI Foundry anche in locale** (`DefaultAzureCredential`); SAS Viya/SVI non gira in locale (`SVI_MODE=mock`). In locale usare **solo dati sintetici**.

## Struttura del progetto

```
admin-console/          Console React (admin / configurazione / observability)
services/
  api/                  Back-end FastAPI (edge, unico confine di fiducia)
  worker-scraping/      Worker Temporal (scraping) — activity/workflow stub
  llm-gateway/          Gateway verso Azure AI Foundry (DefaultAzureCredential)
  svi-publisher/        Pubblicazione in SAS Visual Investigator (mock | live)
docker-compose.dev.yml  Ambiente locale (Docker Desktop)
docs/                   Documentazione tecnico-funzionale e di architettura
```

Lo scaffold è uno **scheletro eseguibile**: i servizi partono e comunicano; la logica di dominio è a placeholder (marcata `TODO`).

## Sincronizzazione e modello di branch

| Branch | Ruolo |
|--------|-------|
| `main` | Branch **stabile** — target di sincronizzazione del repo locale |
| `claude/web-scraping-reputation-pa-c8r9rq` | Branch di **sviluppo** — le modifiche vengono poi consolidate su `main` |

**Repo locale (clone):**
```bash
git clone https://github.com/itacrg-ops/Web_scraping.git
cd Web_scraping
cp .env.example .env        # poi valorizzare le variabili (mai committare .env)
```

**Flusso quotidiano:**
```bash
git pull origin main                 # allineamento alla base stabile
# ...lavoro sul branch di sviluppo...
git add -A && git commit -m "..."
git push origin <branch-di-sviluppo>
```

L'ambiente Claude Code sul web è **effimero**: l'unica copia durevole è su GitHub. Il repo locale si sincronizza esclusivamente via `git pull`/`push`.

## Stato

Repository in fase di **avvio**: documentazione tecnico-funzionale completa e **scaffolding eseguibile** dell'ambiente locale (console admin, back-end a microservizi, gateway Foundry, publisher SVI con mock, orchestrazione Temporal). Le fasi implementative del dominio (Entity Resolution, scraper conforme, classificazione FATF, AMI scoring, integrazione SVI reale) sono descritte nel piano di sviluppo del documento tecnico e marcate `TODO` nel codice.
