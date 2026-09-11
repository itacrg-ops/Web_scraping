# Configurare un dominio "Adverse Media" in SAS Visual Investigator

Guida operativa per predisporre lato **SVI** ciò che serve a ricevere gli alert
dell'Adverse Media Screening. È un'attività di **solution-design/amministrazione
SVI** (data model → dominio → coda/alert), da svolgere con un profilo
**amministratore** nell'app di amministrazione di SAS Visual Investigator.

> **Perché serve.** In SVI un alert **non è un oggetto libero**: è legato a un
> **dominio** e a un'**entità azionabile** che deve esistere nel modello dati, e va
> in una **coda** che accetta alert manuali/esterni. Il demo generico (domini
> `travelAndExpense`/`pidomain`/`svidomain`, entità `employee`…) non ha nulla di
> "adverse media" e **nessuna** delle sue code accetta alert manuali: per questo va
> configurato un dominio dedicato.

> **Nota sulle versioni.** Le etichette esatte dei menu variano tra le versioni di
> SVI (10.x vs SAS Viya "2025.xx"). Sotto trovi i **nomi delle funzioni** confermati
> dalla documentazione; il riferimento autorevole è l'*Administrator's Guide* (link
> in fondo). I passi sono concettuali e vanno adattati alla tua UI.

## 0. Dove si configura (orientamento nell'amministrazione)

L'amministrazione di SVI è nell'app **Manage Investigate and Search** (area
Administration). Punti che useremo:

- **Data Objects** (pagina iniziale dell'amministrazione): qui si creano e gestiscono
  gli **Entity Type** (object type) con i loro attributi, e si abilita il pulsante
  **Create Alert** per un object type. Le entità possono essere **internal** (gestite
  da SVI — usa questa per `soggetto`) o **external** (da sistemi sorgente).
- **Alerting / Triage** (gestione code): si creano le **Queue** e le **dispositions**;
  nelle *Settings* della coda si abilita **"Allow Manually created alerts to be routed
  to the queue"**.
- *(opz.)* **Page Builder / Manage Pages**: le schermate per gli investigatori.

> Le etichette esatte cambiano con la versione. Alternativa **via API**: SVI espone
> una **AdminMetadataApi** per definire gli entity type programmaticamente (posso
> aiutarti a scriptarla se preferisci non usare la UI). Per i click con screenshot,
> il riferimento è il *Tutorials and Examples* della tua versione.

## 1. Concetti SVI (mappati sul nostro caso)

| Concetto SVI | Cos'è | Nel nostro caso |
|---|---|---|
| **Object type** (data model) | Tipo di entità con attributi | `soggetto` (impresa/persona sotto screening) |
| **Dominio / strategia** | Raggruppa object type, code, alert, sicurezza | `adverseMedia` |
| **Alert** | Segnalazione su un'entità azionabile | l'alert AMI del nostro screening |
| **Queue (coda)** | Dove atterrano gli alert per la revisione | `am_primo_livello` (I livello) |
| **Disposition** | Esiti selezionabili su un alert | Avvia istruttoria / Chiudi / Sospendi |
| **Manual alert** | Alert creato dall'esterno/analista (non da scenario) | il canale che usiamo dal publisher |

Gli alert del demo erano generati da **scenari/Intelligent Decisioning**; noi
invece **spingiamo** l'alert già calcolato (AMI a monte) → serve il canale
**manual alert**, che va abilitato sulla coda e sull'object type.

## 2. Modello dati — object type `soggetto`

Nell'amministrazione SVI (**Manage Data** / **Data Model**) crea un object type e i
suoi attributi. Proposta allineata ai campi che il publisher può inviare:

| Attributo SVI (proposto) | Tipo | Da (nostro campo) | Note |
|---|---|---|---|
| `denominazione` | string | denominazione / subject | label dell'entità |
| `codiceFiscalePIVA` | string | cf_piva | **chiave** identificativa |
| `tipoSoggetto` | string | tipo_soggetto | persona_fisica / _giuridica |
| `cup` | string (multi) | cup[] | intervento/i FSC |
| `ruolo` | string | ruolo | RUP, esecutrice, … |
| `luogoNascita` | string | luogo_nascita | solo persona fisica |
| `dataNascita` | date | data_nascita | solo persona fisica |

Imposta `codiceFiscalePIVA` come **identificativo univoco** (serve come
`actionableEntityId`) e `denominazione` come **label** (`actionableEntityLabel`).
Indicizza l'object type per la ricerca se previsto dalla tua versione.

## 3. Attributi dell'alert (custom)

Se la tua versione consente attributi custom sull'alert (o su un **alert type**
dedicato), definisci quelli che portano l'esplicabilità del nostro AMI:

| Attributo alert (proposto) | Tipo | Da |
|---|---|---|
| `amiScore` | number | ami_score → mappato su `initialScore` |
| `riskLevel` | string | risk_level (ALTO/MEDIO/BASSO) |
| `fatfCategories` | string (multi) | fatf_categories |
| `disposizioneProposta` | string | disposition |
| `motivazione` | text | drivers (rationale) |
| `evidenze` | text/link | evidence (URL, hash, testata) |

Se invece la versione non permette attributi custom sull'alert, questi dati
restano nell'entità/nel campo note dell'alert: lo decidiamo in fase di aggancio.

## 4. Dominio / strategia `adverseMedia`

Crea (o riusa) un **dominio** e associaci l'object type `soggetto`, la coda e la
sicurezza. Annota l'**id del dominio**: sarà il `domainId` degli alert
(es. `adverseMedia`).

## 5. Coda `am_primo_livello` (con alert manuali)

1. Crea una **queue** nel dominio (es. `am_primo_livello`).
2. Nelle **Settings** della coda, spunta **"Allow Manually created alerts to be
   routed to the queue"** → è il flag `acceptManualAlerts=true` che ci manca oggi.
3. Definisci le **dispositions** (esiti) coerenti col nostro processo, es.:
   `Avvia istruttoria`, `Chiudi (nessun rischio)`, `Sospendi/Richiedi verifica`.
4. Assegna i permessi ai gruppi che faranno la revisione (istruttori I livello).

## 6. Abilita la creazione manuale sull'object type

Nella pagina **Data Objects** dell'amministrazione, **assegna il pulsante
"Create Alert"** all'object type `soggetto`. È il passo che, insieme al flag della
coda, abilita la creazione di alert (manuali/esterni) su quelle entità — sia da UI
sia via **Alerts API**.

## 7. (Opzionale) Pagine e ricerca

Con il **Page Builder** disegna la scheda del `soggetto` e la vista alert per gli
istruttori (campi, evidenze, link). Non è bloccante per il primo alert, ma serve
per l'operatività.

## 8. Aggancio con il publisher (dopo la config)

A dominio pronto, il flusso del nostro `svi-publisher` diventa:

1. **carica/aggiorna l'entità** `soggetto` nel Data Hub (`POST /svi-datahub/documents`),
   con `codiceFiscalePIVA` come chiave (upsert idempotente);
2. **crea l'alert** (`POST /svi-alert/alerts`) su quell'entità, nella coda
   `am_primo_livello`, con `initialScore = amiScore`.

Valori da riportarmi (li metto in `.env` e completo il mapping del payload sullo
schema reale):

```dotenv
SVI_DOMAIN_ID=adverseMedia            # id del dominio (passo 4)
SVI_ENTITY_TYPE=soggetto              # object type (passo 2)
SVI_QUEUE=am_primo_livello            # id coda con manual alerts ON (passo 5)
# eventuale codice "origine" per gli alert manuali, se richiesto dalla tua versione
SVI_ALERT_ORIGIN=
```

> A quel punto riscrivo `mapping.build_alert`/`build_document` sullo schema reale
> (`domainId`, `actionableEntityType/Id/Label`, `initialScore`, coda) e proviamo
> `--create`: l'alert deve comparire nella console SVI, nella coda del I livello.

## 9. Verifica

- La coda `am_primo_livello` compare tra quelle che **accettano alert manuali**
  (nel nostro smoke-test: `acceptManualAlerts=true`).
- Un `soggetto` di prova è ricercabile in SVI.
- `svi_smoketest.py --create` crea l'alert e lo si vede in coda con score e
  motivazione; le **dispositions** sono selezionabili.

## Riferimenti

- [SAS Visual Investigator — Administrator's Guide](https://documentation.sas.com/api/docsets/visgatorag/v_039/content/visgatorag.pdf) — capitoli su *Entity Types* e *Data Object Types*
- [SAS Visual Investigator — Tutorials and Examples](https://documentation.sas.com/api/docsets/visgatorex/10.5/content/visgatorex.pdf) — esempi passo-passo con screenshot
- [SAS Visual Investigator — AdminMetadataApi](https://developer.sas.com/apis/vi/apiDocs/AdminMetadataApi.html) — definizione entity type via API
- [Creare alert manualmente in Visual Investigator (SAS Communities)](https://communities.sas.com/t5/SAS-Communities-Library/Can-I-Create-Alerts-Manually-in-Visual-Investigator-Yes-as-of/ta-p/396109)
- [Visual Investigator Alerts API](https://developer.sas.com/rest-apis/svi-alert)
- [SAS Visual Investigator — Data Dictionary](https://support.sas.com/documentation/prod-h/visgator/vidd/106/SASVisualInvestigator10.6.pdf)

> Le etichette dei menu dipendono dalla versione: usa i **nomi delle funzioni** qui
> sopra come guida e l'Administrator's Guide della tua versione come riferimento.
