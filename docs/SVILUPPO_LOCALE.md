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
| entity-resolution | http://localhost:8070/healthz | gate anti-omonimia (entità **e persone fisiche**) |
| search-gateway | http://localhost:8095/healthz | ricerca articoli (`mock` default, `gdelt` keyless) |
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

## Provare lo screening — persona giuridica e persona fisica
Dalla console (tab **Screening**) si sceglie il tipo di soggetto:

- **Persona giuridica**: `denominazione` + eventuale `CF/P.IVA`. Il match forte è
  la P.IVA (11 cifre) o il CF (11/16) in registro.
- **Persona fisica** (ricerca per **nome e cognome**): `cognome` + `nome`, con
  `Codice Fiscale` (16) o `data di nascita` per disambiguare l'**omonimia**.

Regola anti-omonimia (gate §8): **solo un identificatore forte supera il gate**
di default. Il solo nome porta a `needs_review`/`ambiguous` (revisione umana); la
data di nascita restringe i candidati ma **non risolve da sola**; il **CF** risolve
in modo deterministico, ma se è indicata **anche** una data di nascita
**discordante** il gate non passa (`needs_review`: input contraddittorio).

Soggetti nel registro seed (`services/entity-resolution/app/resolver.py`):

| Soggetto | Tipo | Identificatore forte | Data di nascita |
|----------|------|----------------------|-----------------|
| ACME Costruzioni S.r.l. | giuridica | P.IVA `00743110157` | — |
| Rossi Mario (#1) | fisica | CF `RSSMRA75C15H501P` | 1975-03-15 |
| Rossi Mario (#2, omonimo) | fisica | CF `RSSMRA80E20F205I` | 1980-05-20 |
| Bianchi Giulia | fisica | CF `BNCGLI82S43H501W` | 1982-11-03 |

Esiti attesi (persona fisica "Rossi Mario", che ha un **omonimo**):

| Input | Esito |
|-------|-------|
| solo nome e cognome | `ambiguous` (due omonimi) |
| nome + cognome + data `1975-03-15` (senza CF) | `needs_review` (ridotto a 1, ma serve conferma) |
| CF `RSSMRA80E20F205I` (senza data) | `resolved` (il CF basta) |
| CF `RSSMRA80E20F205I` + data `1980-05-20` (coerente) | `resolved` |
| CF `RSSMRA80E20F205I` + data `1975-03-15` (**discordante**) | `needs_review` (incoerenza CF/data) |

Per la persona giuridica: "ACME" solo nome → `ambiguous` (c'è anche "ACME … Generali");
con P.IVA `00743110157` → `resolved`.

> I CF del seed sono **fittizi ma formalmente validi** (checksum). In produzione
> il registro proviene da ReGiS/OpenCoesione/InfoCamere (beneficiari/attuatori e
> relativi UBO/RUP/rappresentanti).

### Ricerca articoli (web search)
Dopo aver indicato il soggetto, il pulsante **Cerca articoli** interroga il
`search-gateway` e mostra i candidati (titolo, testata, data, snippet). Da lì:

- **selezioni** uno o più articoli → screening solo su quelli (`seed_urls`);
- **URL singolo** nel campo override → screening solo di quell'URL (`seed_url`);
- **nessuna selezione né URL** → il workflow fa la **ricerca automatica** e
  screena i primi N (default 3, `max_articles`).

In tutti i casi la pipeline verifica la **menzione** del soggetto in ogni
articolo e produce **un alert con più evidenze** (una per articolo recuperato e
con hash). La query di ricerca è nome/denominazione + termini avversi FATF
(indagato, corruzione, sequestro, …).

**Deduplica per dominio e credibilità delle testate** (§5.1). I risultati sono:
- **deduplicati per dominio** (`MAX_PER_DOMAIN=1`): un articolo per testata, per
  favorire la corroborazione da fonti indipendenti;
- **annotati con la credibilità** della testata (alta | media | bassa |
  sconosciuta) da un registro governabile (`services/search-gateway/app/testate.py`)
  e **ordinati** con le fonti più affidabili in cima;
- **filtrabili** sotto una soglia: toggle *"Solo testate affidabili (≥ media)"* in
  console, oppure `MIN_CREDIBILITY=media` nel `.env` (default `none` = solo
  annotazione). La credibilità della fonte viene propagata all'**evidenza**
  dell'alert (percorso di ricerca automatica).

Provider (`SEARCH_PROVIDER` nel `.env`):
- **`mock`** (default): risultati di esempio, nessuna rete — utile per l'anteprima
  e il wiring. Include un duplicato di dominio (per mostrare la dedup) e una testata
  a bassa credibilità (per mostrare il filtro). Gli URL `*.example` non risolvono
  (il fetch reale darà poco segnale).
- **`gdelt`** (keyless): news reale globale, adatta al pilota. Nessuna API key.
  ```bash
  SEARCH_PROVIDER=gdelt docker compose -f docker-compose.dev.yml up -d --build search-gateway
  ```
  Filtri: `SEARCH_DEFAULT_LANG` (lingua GDELT, es. `italian`) e `SEARCH_TIMESPAN`
  (es. `24h`, `1w`, `3m`, `6m`). Altri provider (Bing/Brave/SerpAPI/Google CSE via
  API key, o feed licenziati Dow Jones/Factiva) si innestano su
  `services/search-gateway/app/providers.py`.

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
  worker-scraping/      Worker Temporal: pipeline di screening (gate ER incluso)
  entity-resolution/    Gate anti-omonimia (normalizzazione, CF/P.IVA, matching)
  llm-gateway/          Gateway verso Azure AI Foundry (DefaultAzureCredential)
  svi-publisher/        Pubblicazione in SAS Visual Investigator (mock|live)
docker-compose.dev.yml  Ambiente locale
docs/                   Documentazione tecnico-funzionale e di architettura
```

## Stato dello scaffold
Scheletro **eseguibile e in crescita**. Già reali: persistenza su PostgreSQL,
**web search** degli articoli adverse-media (`search-gateway`: mock in locale,
GDELT keyless nel pilota; screening auto dei top-N o su articoli scelti),
**Entity Resolution** (gate anti-omonimia con validazione CF/P.IVA, per **entità
e persone fisiche** — ricerca per nome e cognome con disambiguazione per CF/data
di nascita), **fetch
conforme** (robots.txt + crawl-delay, User-Agent identificabile, rate-limiting
per dominio, snapshot **WARC** su object store con hash SHA-256 e provenance) ed
estrazione con trafilatura, **Evidence** persistita e ancorata all'alert, e
**classificazione FATF dual-LLM strutturata** via Azure AI Foundry (categorie,
ruolo processuale, Victim-Bystander, severità, confidence; vedi
[FOUNDRY_SETUP.md](FOUNDRY_SETUP.md)) con fallback euristico se Foundry non è
configurato, e **verifica di menzione** non bloccante (anti falsa attribuzione:
segnala se il soggetto non è citato nell'evidenza). Placeholder / da completare
(marcati `TODO`): AMI scoring governato in SAS Viya (oggi mappatura locale
severità→AMI), mapping reale del Data Hub/Alerts SVI, headless browser per
pagine dinamiche.

Gli snapshot delle pagine (HTML + WARC) sono su MinIO (console http://localhost:9001,
bucket `adverse-media-snapshots`).

## Troubleshooting

**La console non riflette le modifiche al codice.**
La `admin-console` in locale **non è un'immagine buildata**: gira come **Vite
dev server** (`node:20-alpine`) con la sorgente montata come volume. Quindi
`docker compose up --build` **non** la rigenera (ricostruisce solo i servizi
Python). Se le modifiche non compaiono:
1. Verifica di avere il codice aggiornato: `git log --oneline -1` nel repo.
2. Ricrea il container della console:
   ```bash
   docker compose -f docker-compose.dev.yml up -d --force-recreate admin-console
   ```
3. **Hard refresh** del browser (Ctrl/Cmd+Shift+R).

L'HMR su bind mount di Docker Desktop usa il **polling** (`vite.config.ts`,
`server.watch.usePolling`): senza, le modifiche potrebbero non essere rilevate.

**Il back-end mostra codice vecchio dopo un `git pull`.** I servizi Python sono
immagini buildate: dopo un pull rigenera con `--build`
(`docker compose -f docker-compose.dev.yml up --build`).

## Promozione in produzione
Stesse immagini, su **Azure/AKS** via Helm (§11.1): store gestiti (Azure
PostgreSQL, Cache for Redis, Blob WORM), identità keyless (Entra + Workload
Identity), Private Endpoint. Vedi il documento di deployment.
