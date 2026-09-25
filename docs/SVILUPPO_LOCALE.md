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

### Redazione PII prima dell'invio all'LLM (B1)
Prima di inviare qualunque testo ad Azure (unico punto di egress:
`llm-gateway/app/foundry.py::classify`), il gateway **redige le PII strutturate**
di terzi — Codice Fiscale, P.IVA, email, IBAN, telefoni — con placeholder
tipizzati (`[CF]`, `[EMAIL]`, …). NON tocca anni, importi, date e numeri di
procedimento (servono alla classificazione FATF). L'audit (conteggi per categoria,
mai i valori) è loggato e restituito nel campo `pii_redaction` della risposta.
- Attivo per default (`PII_REDACTION=true`); `false` solo in ambienti senza egress
  esterno.
- **Nomi di persona (B1.1)**: oltre agli identificatori strutturati, i **nomi**
  vengono pseudonimizzati via NER — il soggetto (persona) → `[SOGGETTO]`, i terzi →
  `[PERSONA]` — così ad Azure non arriva alcun nome reale. Il marcatore `[SOGGETTO]`
  aiuta anche l'analisi Victim-Bystander. Sotto-flag `REDACT_PERSON_NAMES` (default
  attivo); senza NER si redige almeno il nome noto del soggetto.
- Test: `python services/llm-gateway/tests/test_pii.py`.

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

**Disambiguazione per CUP (B7).** Tra candidati **omonimi**, se lo screening porta
il **CUP** dell'intervento e a registro un solo omonimo è legato a quel CUP, il
gate lo risolve (`probabilistico_nome_CUP`) invece di fermarsi ad `ambiguous`: non
è "solo nome", è nome + legame autoritativo all'intervento. Disattivabile con
`ALLOW_CUP_DISAMBIGUATION=false`. In opzione, `USE_EMBEDDINGS=true` fonde la
similarità **semantica** dei nomi (embedding via llm-gateway) con quella di stringa
per le varianti/abbreviazioni (richiede `EMBEDDING_MODEL` su Foundry; senza, resta
la sola stringa). Test: `python services/entity-resolution/tests/test_resolver_b7.py`.

**Dati anagrafici della persona fisica (B7).** Tre presidi anti-omonimia aggiuntivi:
- **Coerenza CF ↔ dati anagrafici.** Il Codice Fiscale codifica cognome, nome e
  data di nascita: al gate, se non combaciano con quanto inserito → `needs_review`
  (`incoerenza_CF_dati_anagrafici`); intercetta refusi e CF sbagliati. In console
  un **avviso live** segnala l'incoerenza mentre digiti (endpoint `POST /cf-check`;
  test `tests/test_codice_fiscale.py`).
- **Luogo di nascita** (campo opzionale in Screening e Soggetti, colonna nel CSV):
  ulteriore disambiguatore tra omonimi, come la data di nascita.
- **Estrazione dagli articoli.** Età/anno/luogo di nascita citati nel testo vengono
  confrontati col soggetto: se coincidono, l'identità è corroborata; se discordano
  (es. "45 anni" per un soggetto che ne avrebbe 60), l'alert marca **"possibile
  OMONIMO"**.
- **NER (B7 parte 2).** Il worker chiede la NER italiana al llm-gateway
  (`POST /v1/ner`, spaCy `it_core_news_sm`) e verifica se il soggetto è riconosciuto
  come **persona** e l'azienda come **organizzazione** → corroborazione più robusta
  del match a stringhe (driver *"NER: azienda riconosciuta come organizzazione…"*).
  Toggle `NER_CORROBORATION` (default attivo); **non fatale**: se il modello non è
  installato il gateway risponde `available:false` e si resta sulle stringhe. Lo
  stesso `/v1/ner` abiliterà **B1.1** (redazione dei nomi di terzi prima dell'LLM).

> **Soggetto non a registro** (es. cerchi "Italware" e non è tra i soggetti noti):
> di default il gate resta `unresolved` (HITL) — è corretto, in produzione il
> registro contiene i beneficiari reali. Due modi per procedere:
> 1. **Aggiungilo al registro** dalla tab **Soggetti** con il suo CF/P.IVA →
>    match **deterministico** allo screening (`resolved`). È il flusso di
>    produzione (lì il registro è sincronizzato da ReGiS/OpenCoesione/InfoCamere).
> 2. **Screening esplorativo**: `ALLOW_UNREGISTERED_SUBJECT=true` → il soggetto è
>    risolto come **`provvisorio`** (non autoritativo), utile per provare la
>    pipeline su qualsiasi nome. Non tocca i casi ambigui.

Il **registro soggetti** è persistito su PostgreSQL (sistema di record dell'API)
e gestibile dalla tab **Soggetti**: aggiungi, **modifica in linea** (icona
matita → salva/annulla, incluso il flag *attivo*), elimina e **importa da CSV**.
L'entity-resolution lo legge dall'API con una cache breve (`REGISTRY_TTL`,
default 30s), quindi le modifiche diventano effettive entro pochi secondi.

**Import CSV** (bottone *Importa CSV*, template scaricabile): header
`tipo_soggetto,denominazione,nome,cognome,cf_piva,data_nascita,cup,ruolo`
(più CUP nella stessa cella separati da `;`). L'import fa **upsert per CF/P.IVA**
(aggiorna se presente, altrimenti crea) e riporta righe create/aggiornate/errori.
Per la persona fisica la denominazione è composta come "Cognome Nome". È la base
per una futura **sincronizzazione da ReGiS/OpenCoesione/InfoCamere**.

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

Per collaudare **tutti** questi casi in un colpo solo (senza cliccare in console):
`python scripts/smoke_entity_resolution.py` — interroga `POST /resolve` e stampa
PASS/FAIL per ciascun caso (nell'intestazione dello script l'uso via Docker se non
hai Python sull'host). Assume il registro seed di default.

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
con hash).

**Come si cerca.** Prima nome/denominazione + termini avversi FATF (indagato,
corruzione, sequestro, …), poi il **solo nome**: con Brave e SearXNG i risultati delle
due query si **sommano** (senza doppioni) finché non bastano, e quelli trovati con i
termini avversi vanno in cima (in console: chip «termini avversi»). Prima la ricerca si
fermava alla prima query con almeno un risultato: con «nome + 8 termini avversi», che i
motori web vogliono tutti presenti, spesso ne restava uno solo. Eccezione: persona con
azienda/località (qui sotto), dove ci si allarga solo se non si trova nulla. Sotto i
risultati la console mostra **cosa ha fatto ogni motore**: quanti risultati, quali query,
errori e motori di SearXNG «senza risposta» (es. «bing news: pagina non leggibile»). Un
motore senza risposta è normale se gli altri trovano risultati: non compare come avviso.

**Qualificatori persona fisica (anti-omonimia).** Per una persona si possono
indicare (opzionali) **Azienda** e **Località**: entrano nella query come
qualificatori **in AND forte** (`"Mario Rossi" "Italware" "Cagliari"`) e, quando
presenti, i termini avversi non sono più obbligatori (il recall resta alto, è la
classificazione FATF a stabilire l'adverse). **Se l'AND forte non trova nulla**
(caso frequente: nessuna pagina indicizzata cita nome e azienda insieme), la
ricerca **si allarga automaticamente** — toglie un qualificatore alla volta
(prima la località, poi l'azienda) fino al solo nome — così non si resta mai a
zero; la console segnala che ha allargato la ricerca e la corroborazione a valle
(qui sotto) distingue comunque il soggetto dagli omonimi. Il **Ruolo** è invece *soft*: non
filtra la ricerca (da solo taglierebbe articoli), ma viene usato — con
azienda/località — come **corroborazione sull'articolo**: se co-occorrono col
nome, la probabilità di omonimia cala (driver "Contesto confermato"); se il nome
compare senza alcun contesto, l'alert è marcato "⚠ possibile omonimo".

**Deduplica per dominio e credibilità delle testate** (§5.1). I risultati sono:
- **ripuliti dai siti che non sono notizie**: schede e bilanci d'impresa, elenchi,
  social, annunci di lavoro (`testate.NON_NOTIZIE`; altri con `SEARCH_EXCLUDE_DOMAINS`),
  e dalle pagine di elenco dei giornali (tag, argomento, ricerca interna: titoli di altri
  articoli, non un articolo);
- **deduplicati per dominio** (`MAX_PER_DOMAIN=1`): un articolo per testata, per
  favorire la corroborazione da fonti indipendenti;
- **annotati con la credibilità** della testata (alta | media | bassa |
  sconosciuta) da un registro governabile (`services/search-gateway/app/testate.py`)
  e **ordinati** con le fonti più affidabili in cima;
- **filtrabili** per credibilità: toggle *"Escludi fonti a bassa credibilità"* in
  console (scarta solo le testate note come poco affidabili — blog/UGC — e
  mantiene le *sconosciute*, cioè non ancora a registro), oppure `MIN_CREDIBILITY`
  nel `.env` (`none` default = solo annotazione; `media` = whitelist stretta).
  Ordine credibilità: `alta > media > sconosciuta > bassa`. La credibilità della
  fonte viene propagata all'**evidenza** dell'alert.

> Con `SEARCH_PROVIDER=gdelt`: il nome dell'ente viene ripulito dalla forma
> societaria per la ricerca (es. *"Tron Group Holding S.r.l."* → cerca
> *"Tron Group Holding"*), e se la query mirata non trova nulla il gateway
> **ripiega** su nome-solo e poi senza vincolo di lingua. Se resti a 0: prova un
> nome più breve, disattiva il filtro credibilità o allarga `SEARCH_TIMESPAN`.
>
> **GDELT è rate-limited** (~1 richiesta ogni pochi secondi per IP): se hai
> ricerche ravvicinate può rispondere **429**. Il gateway distanzia le chiamate
> (`GDELT_MIN_INTERVAL`, default 5s) e su 429 fa **un solo retry**; se persiste,
> la console mostra un avviso «GDELT ha limitato le richieste» — attendi qualche
> secondo e riprova. La preview può quindi impiegare qualche secondo.

Provider (`SEARCH_PROVIDER` nel `.env`):
- **`mock`** (default): risultati di esempio, nessuna rete — utile per l'anteprima
  e il wiring. Include un duplicato di dominio (per mostrare la dedup) e una testata
  a bassa credibilità (per mostrare il filtro). Gli URL `*.example` non risolvono
  (il fetch reale darà poco segnale).
- **`gdelt`** (keyless): news reale globale, **ma rate-limited/instabile** (può
  rispondere 429 anche da fermo, sotto carico). Va bene per prove occasionali, non
  per un uso intensivo. Filtri: `SEARCH_DEFAULT_LANG`, `SEARCH_TIMESPAN`.
- **`brave`** (a chiave, **affidabile** — consigliato per il pilota): Brave Search
  API. Ottieni una chiave free su <https://brave.com/search/api>, poi:
  ```bash
  # nel .env: SEARCH_PROVIDER=brave e BRAVE_API_KEY=...
  docker compose -f docker-compose.dev.yml up -d --build search-gateway
  ```
- **`searxng`** (meta-search self-hosted, **keyless**): aggrega più motori. Cerca sia
  nel **web** (categoria `general`: Google tramite Custom Search, DuckDuckGo, Brave —
  trova anche articoli di anni fa, sentenze, provvedimenti) sia nelle **notizie**
  (`news`: Google/Bing/DuckDuckGo/Brave News e Il Post, che cerca nel proprio archivio;
  esclusi startpage, che chiede il CAPTCHA, e ANSA, che risponde con errori HTTP). Gira
  come servizio nel compose; la configurazione (API JSON abilitata, motori,
  `search-gateway/searxng/settings.yml`) è **inclusa nell'immagine** e letta da
  `SEARXNG_SETTINGS_PATH`, non montata: dopo una modifica al file,
  `docker compose -f docker-compose.dev.yml up -d --build searxng`. La **versione** di
  SearXNG è fissata (digest nel `Dockerfile`), quella su cui è verificata la
  configurazione: con `latest` la build riusava un'immagine già scaricata, anche vecchia
  di mesi, con motori rotti. Per aggiornarla si cambia il digest e si ricostruisce.
- **Persone giuridiche con nomi comuni** («Vita Srl», «Nuova Vita S.p.A.»): la ricerca
  usa la denominazione con la forma giuridica (mai la sola parola «vita») e mette prima
  i risultati che la citano per intero; nell'articolo il nome conta solo se usato come
  nome proprio o in contesto societario («la Vita Srl», «la società Vita»).
- **Multi-provider (B8)**: metti una **lista** in `SEARCH_PROVIDER`
  (es. `searxng,gdelt,brave`) → **fan-out parallelo** con timeout per provider,
  **merge + dedup per URL** e **boost di corroborazione** (un URL trovato da più
  motori sale in cima; il campo `provider` diventa es. `gdelt+searxng` e
  `corroborations` conta i motori). Se tutti tornano a vuoto, la risposta è vuota
  (nessun fallback al mock, per non introdurre dati finti). Consigliato: `searxng,gdelt`.
- Altri provider (SerpAPI/Google CSE, o feed licenziati Dow Jones/Factiva) si
  innestano su `services/search-gateway/app/providers.py`.

### AMI: pesatura per credibilità e corroborazione
L'AMI non dipende solo dalla gravità: **AMI = base(severità) × credibilità ×
corroborazione**, poi cap Victim-Bystander e clamp 0–100.
- **credibilità**: dalla testata migliore tra le fonti che citano il soggetto —
  `alta ×1.05`, `media ×1.00`, `sconosciuta ×0.95` (cautela lieve: testata non a
  registro), `bassa ×0.80`;
- **corroborazione**: numero di **domini distinti** che citano il soggetto —
  0 → ×0.50 (possibile falsa attribuzione), 1 → ×0.95, 2 → ×1.00, 3 → ×1.07,
  ≥4 → ×1.15. Due articoli della **stessa** testata contano come una fonte.

La formula è **esplicabile**: ogni fattore compare nei *driver* dell'alert (es.
«AMI = base 88 (severità alta) × 1.00 (credibilità) × 0.95 (corroborazione) = 84»).
I pesi sono `services/worker-scraping/activities.py` (in prod: governo in SAS Viya).

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
estrazione con trafilatura (con **fallback headless** Playwright per le pagine
JS-rendered, B6), **Evidence** persistita e ancorata all'alert, e
**classificazione FATF dual-LLM strutturata** via Azure AI Foundry (categorie,
ruolo processuale, Victim-Bystander, severità, confidence; vedi
[FOUNDRY_SETUP.md](FOUNDRY_SETUP.md)) con fallback euristico se Foundry non è
configurato, e **verifica di menzione** non bloccante (anti falsa attribuzione:
segnala se il soggetto non è citato nell'evidenza), **AMI pesato** per
**credibilità** della testata e **corroborazione** (numero di fonti indipendenti
che citano il soggetto), con formula esplicabile nei driver dell'alert.
Placeholder / da completare (marcati `TODO`): AMI scoring governato in SAS Viya
(oggi pesatura locale severità × credibilità × corroborazione; mancano
materialità CUP, sentiment, freschezza), mapping reale del Data Hub/Alerts SVI.

Gli snapshot delle pagine (HTML + WARC) sono su MinIO (console http://localhost:9001,
bucket `adverse-media-snapshots`).

### Fallback headless per pagine JS-rendered (B6)
Quando l'estrazione HTTP di un articolo è **povera** (< ~400 caratteri, tipico
delle SPA/JS), il worker rende la pagina con **Chromium headless** (Playwright) e
ri-estrae, tenendo la versione con più testo. Il DOM renderizzato passa per la
**stessa** pipeline snapshot/hash/WARC (evidenza probatoria invariata) e il render
avviene solo su URL già ammessi da robots/crawl-delay. Toggle `HEADLESS_FALLBACK`
(default attivo); l'immagine `worker-scraping` include Chromium (~400 MB in più).
Un driver dell'alert segnala quando una fonte è stata recuperata via headless.

## Troubleshooting

**La console non riflette le modifiche al codice.**
In locale la `admin-console` gira come **Vite dev server** (`admin-console/Dockerfile.dev`):
usa la sorgente montata da `./admin-console` (le modifiche si vedono subito) e, se il
volume arriva vuoto, la **copia inclusa nell'immagine**. Se le modifiche non compaiono:
1. Verifica di avere il codice aggiornato: `git log --oneline -1` nel repo.
2. Guarda come è partita: `docker compose -f docker-compose.dev.yml logs admin-console | head`.
   Se dice che il volume **arriva VUOTO**, sta usando la copia dell'immagine: ricostruiscila
   dopo ogni `git pull` (sotto) oppure risolvi il volume (punto successivo).
3. Ricostruisci e ricrea il container della console:
   ```bash
   docker compose -f docker-compose.dev.yml up -d --build --force-recreate admin-console
   ```
4. **Hard refresh** del browser (Ctrl/Cmd+Shift+R).

**Volume della console vuoto** («il volume ./admin-console arriva VUOTO nel container»).
Docker non vede la cartella del progetto: gli altri servizi funzionano perché sono
immagini costruite (il contesto di build lo legge il client Docker), mentre il volume
richiede che la cartella sia condivisa con Docker Desktop. Controlla:
- di lanciare `docker compose` dalla **cartella del repository** (`ls admin-console/package.json`);
- Docker Desktop → *Settings → Resources → File sharing*: la cartella (o il disco) del
  progetto deve essere condivisa; con WSL 2, meglio tenere il repository nel file system
  di WSL e lanciare `docker compose` da lì;
- cartelle sincronizzate (OneDrive/iCloud) con file «solo online»: rendili disponibili offline.
Poi `docker compose -f docker-compose.dev.yml up -d --force-recreate admin-console`: nel log
deve comparire «sorgente montato».

L'HMR su bind mount di Docker Desktop usa il **polling** (`vite.config.ts`,
`server.watch.usePolling`): senza, le modifiche potrebbero non essere rilevate.

**La ricerca trova meno articoli di Google.** Guarda sotto i risultati cosa ha fatto
ogni motore. «Senza risposta: google cse: CAPTCHA/timeout» = il motore ha bloccato le
richieste (troppe in poco tempo): riprova più tardi o aggiungi Brave
(`SEARCH_PROVIDER=searxng,brave`, con `BRAVE_API_KEY`). «Pagina non leggibile» o «errore
HTTP» sempre sullo stesso motore = il sito ha cambiato le sue pagine: serve una versione
più recente di SearXNG (digest nel `Dockerfile`) o si esclude il motore
(`use_default_settings.engines.remove` in `settings.yml`). Se un motore trova molti
risultati ma in lista ne restano pochi, sono stati tolti i doppioni della stessa testata
e i siti che non sono notizie (il numero dei «rimossi» è accanto al totale).

**Il back-end mostra codice vecchio dopo un `git pull`.** I servizi Python sono
immagini buildate: dopo un pull rigenera con `--build`
(`docker compose -f docker-compose.dev.yml up --build`).

**«searxng: SearXNG ha risposto 403»** nella pagina Screening. SearXNG sta usando la sua
configurazione di default, che non abilita il formato JSON. Succedeva quando `settings.yml`
era montato come volume e il volume arrivava vuoto (come per la console); e anche dopo
averla inclusa nell'immagine in `/etc/searxng`, perché l'immagine dichiara quella
cartella come volume e Compose, ricreando il container, vi rimontava la vecchia
configurazione. Ora SearXNG legge la configurazione da un altro percorso dell'immagine
(`SEARXNG_SETTINGS_PATH`): basta ricostruire il servizio.
```bash
docker compose -f docker-compose.dev.yml up -d --build searxng
curl -s "http://localhost:8888/search?q=test&format=json" | head -c 200   # JSON, non 403
```
Se resta 403, il servizio è di una versione precedente: ricrealo da zero con
`docker compose -f docker-compose.dev.yml rm -sf searxng` e poi di nuovo `up -d --build searxng`.
Un **429** invece è il limite di richieste dei motori a monte: riprova più tardi o
aggiungi un altro provider (`SEARCH_PROVIDER=searxng,gdelt`).

## Promozione in produzione
Stesse immagini, su **Azure/AKS** via Helm (§11.1): store gestiti (Azure
PostgreSQL, Cache for Redis, Blob WORM), identità keyless (Entra + Workload
Identity), Private Endpoint. Vedi il documento di deployment.
