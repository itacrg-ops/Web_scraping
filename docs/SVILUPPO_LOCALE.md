# Sviluppo locale (Docker Desktop)

Ambiente locale del pilota Adverse Media Screening. Architettura e razionale:
[DEPLOYMENT_E_INTEGRAZIONE_SAS.md](DEPLOYMENT_E_INTEGRAZIONE_SAS.md) (§11.2).

## Prerequisiti
- **Docker Desktop** (Kubernetes non necessario).
- Una risorsa **Azure AI Foundry**/Azure OpenAI in region UE e un **service principal di sviluppo** (per la classificazione LLM, usata anche in locale).
- `make` (opzionale, per i comandi abbreviati).

## Avvio rapido
```bash
cp .env.example .env
#  valorizza almeno: AZURE_FOUNDRY_ENDPOINT, LLM_MODEL_PRIMARY/SECONDARY,
#  AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET (service principal dev)
docker compose -f docker-compose.dev.yml up --build
#  oppure:  make up
```

Servizi esposti:

| Servizio | URL | Note |
|----------|-----|------|
| admin-console (React) | http://localhost:5173 | config/observability |
| api (FastAPI) | http://localhost:8000/docs | back-end edge |
| llm-gateway | http://localhost:8080/healthz | verso Azure AI Foundry |
| svi-publisher | http://localhost:8090/healthz | `SVI_MODE=mock` in locale |
| Temporal UI | http://localhost:8233 | orchestratore (dev server) |
| MinIO console | http://localhost:9001 | object store (WARC) |

## LLM su Foundry anche in locale
Il `llm-gateway` usa `DefaultAzureCredential`: **lo stesso codice** vale in locale
e in produzione, cambia solo la sorgente della credenziale.
- **Locale**: service principal di sviluppo → variabili `AZURE_TENANT_ID`,
  `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` nel `.env`; endpoint **pubblico** della
  risorsa Foundry.
- **Produzione**: **AKS Workload Identity** (nessuna chiave), Private Endpoint.

> ⚠️ In locale usare **solo dati sintetici / di test**: nessun dato reale
> personale o giudiziario deve uscire da una postazione di sviluppo verso Foundry
> (vincolo DPIA, §10.4 del doc di deployment).

Senza credenziali configurate i servizi partono comunque (gli `/healthz`
rispondono); solo la classificazione LLM restituirà un 503 esplicito.

## SAS Viya / SVI in locale
SVI/Viya **non gira** su Docker Desktop. Due modalità:
- **Mock (default)**: `SVI_MODE=mock` — `svi-publisher` logga gli alert senza
  chiamare SVI. Permette di sviluppare l'intera pipeline senza SAS.
- **Live**: con un ambiente Viya di **test** raggiungibile, impostare
  `SVI_MODE=live`, `VIYA_ENDPOINT`, e avviare col profilo SAS:
  ```bash
  docker compose -f docker-compose.dev.yml --profile sas up --build   # make up-sas
  ```

## Struttura del repository
```
admin-console/          Console React (admin/config/observability)
services/
  api/                  Back-end FastAPI (edge, unico confine di fiducia)
  worker-scraping/      Worker Temporal (scraping) — activity/workflow stub
  llm-gateway/          Gateway verso Azure AI Foundry (DefaultAzureCredential)
  svi-publisher/        Pubblicazione in SAS Visual Investigator (mock|live)
docker-compose.dev.yml  Ambiente locale
docs/                   Documentazione tecnico-funzionale e di architettura
```

## Stato dello scaffold
È uno **scheletro eseguibile**: i servizi partono e comunicano, ma la logica di
dominio è a placeholder (activity di scraping, classificazione FATF, AMI,
persistenza su Postgres, mapping reale del Data Hub/Alerts SVI). I punti da
completare sono marcati con `TODO` nel codice.

## Promozione in produzione
Stesse immagini, su **Azure/AKS** via Helm (§11.1): store gestiti (Azure
PostgreSQL, Cache for Redis, Blob WORM), identità keyless (Entra + Workload
Identity), Private Endpoint. Vedi il documento di deployment.
