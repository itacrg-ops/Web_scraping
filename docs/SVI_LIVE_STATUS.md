# SVI — stato attivazione live (as-built) e blocchi aperti

Handoff dell'integrazione live verso SAS Visual Investigator: cosa è **validato**,
cosa manca e come ripartire. Ambiente di test: **SAS Viya RACE demo**
`https://azureuse030088.race.sas.com`. Runbook operativo: [`SVI_GOLIVE.md`](SVI_GOLIVE.md);
modello dominio: [`SVI_DOMAIN_ADVERSE_MEDIA.md`](SVI_DOMAIN_ADVERSE_MEDIA.md).

## Validato ✅

- **Auth**: OAuth SASLogon con client integrato **`sas.ec`** (secret vuoto), grant
  **password** (utente demo). Token ottenuto (scope amministrativi).
- **TLS**: certificato self-signed → `SVI_VERIFY_TLS=false` (solo demo).
- **Publisher**: `svi-publisher` config-driven; test unitari 7/7.
- **Endpoint di creazione alert individuato**: gli alert **non** si creano con
  `POST /svi-alert/alerts` (405, sola lettura). Si crea un **alerting event**:
  `POST /svi-alert/alertingEvents`, media type
  `application/vnd.sas.investigation.triage.alerting.data.flat+json;version=1`.
- **Struttura del body confermata dall'SVI Admin** ✅ — è un **envelope** con
  discriminatore `jsonLayout:"flat"` e sezioni ad **array** (era il vero motivo del
  `500 tdc.bad.request`: mancavano `jsonLayout` e l'involucro). Forma minima:
  ```json
  {"jsonLayout": "flat",
   "alertingEvents": [
     {"alertingEventId": "<uuid5(businessKey)>",
      "actionableEntityType": "Soggetto", "actionableEntityId": "<CF/P.IVA>",
      "score": 82, "alertTypeCode": "strategy_default",
      "recommendedQueueId": "queue_3264317", "alertTriggerText": "<motivazione>",
      "alertOriginCode": "<opz.>"}],
   "enrichment": [ {"alertingEventId": "…", "ami_score": "82", …} ],          // opz.
   "scenarioFiredEvents": [ {"alertingEventId": "…", "scenarioName": "…", …} ],// opz.
   "contributingObjects": [ {"alertingEventId": "…", "url": "…", …} ]}         // opz.
  ```
  L'oggetto evento **NON** ha `domainId` né `actionableEntityLabel` (il dominio è
  implicito nella coda/strategia). Le tre sezioni opzionali sono gated da config
  (off al primo test). Codice: `mapping.build_alerting_payload()`.
- **Envelope ACCETTATO dal parser** ✅ — con la struttura corretta l'errore è
  **cambiato**: da `500 tdc.bad.request` (rifiuto di struttura/parse, identico anche
  a body vuoto) a **`500 errorCode 1008` "A data error occurred"**. Significa che SVI
  ha superato la validazione della richiesta ed è entrato nell'elaborazione: la
  **forma del payload è giusta**; resta un errore di **dato/riferimento** (vedi sotto).

## Configurazione trovata nell'ambiente

| Cosa | Valore |
|---|---|
| Dominio "Adverse Media" | `domainId = d_42843825` |
| Entity type | `Soggetto` |
| Coda con `acceptManualAlerts=true` | `queue_3264317` |
| Strategia | `strategy_36821163` (⚠ **verificare stato ATTIVO**) |

`.env` corrispondente:
```dotenv
SVI_MODE=live
VIYA_ENDPOINT=https://azureuse030088.race.sas.com
SVI_AUTH_MODE=oauth
SAS_OAUTH_GRANT=password
SAS_CLIENT_ID=sas.ec
SAS_CLIENT_SECRET=
SAS_USERNAME=<utente demo>
SAS_PASSWORD=<password>
SVI_VERIFY_TLS=false
SVI_DOMAIN_ID=d_42843825
SVI_ENTITY_TYPE=Soggetto
SVI_QUEUE=queue_3264317
SVI_ALERT_TYPE_CODE=strategy_default   # tipo alert della strategia (demo: strategy_default)
# Sezioni opzionali dell'envelope (off al primo test, poi abilitabili):
# SVI_SEND_ENRICHMENT=true
# SVI_SEND_SCENARIO_EVENTS=true
# SVI_SEND_CONTRIBUTING_OBJECTS=true
```

## Blocchi aperti (config SVI, **non** codice)

1. **Alerting event → `500 errorCode 1008` "data error"** (dopo aver risolto la
   struttura). La forma è corretta; è un errore di **dato/riferimento**. Cause in
   ordine di probabilità, da isolare con `svi_smoketest.py --diagnose`:
   - **entità inesistente**: `actionableEntity` (`Soggetto` / CF `00743110157`) non
     è un record del Data Hub → l'engine non la risolve → data error. Crearla prima
     (punto 2). ⟵ *sospetto principale*.
   - **`alertTypeCode` non valido** per il dominio Adverse Media: `strategy_default`
     veniva dall'esempio Admin (dominio `tender`), potrebbe non esistere qui. Usare
     un `code` reale dalla discovery (righe `alertType:` dello smoke-test).
   - **strategia INACTIVE/non deployata** → non elabora gli eventi (verificare nelle
     righe `strategy: … state=…`).
   - `recommendedQueueId` inesistente (improbabile: `queue_3264317` verificata).
   Il `--diagnose` invia varianti con omissioni controllate: se l'`errorCode` non
   cambia mai, il problema è entità/strategia (non type/queue).
2. **Creazione entità Soggetto** — `POST /svi-datahub/documents` (`application/json`).
   Confermato: il tipo si passa con **`objectTypeName`** (non `typeName`). Nel Data
   Hub ogni entity type è una **tabella**; il campo obbligatorio non-readonly è
   **`identificativo`** (Name `CodiceFiscalePIVA`), mentre PK `soggetto_id` e
   `version` sono **read-only** (impostati dal server). **Ancora aperto: la
   rappresentazione del body di insert** — né `data{Name/Label}` né top-level /
   `values` / `attributes` / `fields` / array popolano il campo (sempre `DH5104`
   "identificativo mancante"). Va ricavata dalla **doc datahub SAS** o **catturando
   la request reale della UI** (creazione record).

### Data model `Soggetto` (da *Data Objects → Soggetto*)

Nel `data` le chiavi sono la colonna **Name** (non la Label):

| Label | Name | Required | Read-only |
|---|---|:--:|:--:|
| identificativo | `CodiceFiscalePIVA` | ✔ | — |
| Denominazione | `Denominazione` | — | — |
| Tiposoggetto | `TipoSoggetto` | — | — |
| Cup | `CUP` | — | — |
| Ruolo | `Ruolo` | — | — |
| Datanascita | `datanascita` | — | — |
| Luogonascita | `luogoNascita` | — | — |
| Soggetto ID | `soggetto_id` | ✔ | ✔ (PK, server) |
| Version | `version` | ✔ | ✔ (server) |
| Created/Modified By·Date | (sistema) | — | ✔ |

## Strumenti di diagnosi (nel repo)

- `services/svi-publisher/scripts/svi_smoketest.py` — auth + discovery + `--create`.
  Nuovi flag: `--diagnose` (isola il campo che causa il data error, non crea),
  `--unique` (alertingEventId nuovo → esclude collisioni di id). La discovery ora
  elenca `alertType:` (codici validi per `SVI_ALERT_TYPE_CODE`) e `strategy:` (stato).
- `services/svi-publisher/scripts/svi_admin.py` — discovery admin (domini/strategie/
  code/eventi); `--probe` (rivela media type/campi con POST vuoto, non crea);
  `--create-entity` (prova più nomi campo per creare il record `Soggetto`).

Esecuzione (dalla macchina che raggiunge Viya):
```powershell
docker compose -f docker-compose.dev.yml run --build --rm svi-publisher python scripts/svi_smoketest.py --diagnose
docker compose -f docker-compose.dev.yml run --build --rm svi-publisher python scripts/svi_admin.py --create-entity
docker compose -f docker-compose.dev.yml run --build --rm svi-publisher python scripts/svi_smoketest.py --create --unique
```

## Prossimi passi

1. **`svi_smoketest.py --diagnose`** → guarda le righe `alertType:` e `strategy:`
   della discovery (codice alertType valido + stato strategia) e l'esito delle
   varianti: dicono se il `1008` dipende da `alertTypeCode`/`recommendedQueueId`
   oppure da entità/strategia.
2. In base all'esito:
   - `alertTypeCode` sbagliato → mettere in `.env` un `SVI_ALERT_TYPE_CODE` reale;
   - strategia `INACTIVE` → **attivarla/deployarla**;
   - entità mancante → **creare il record `Soggetto` `00743110157`** (punto 2 blocchi;
     `svi_admin.py --create-entity`, o cattura UI dell'off-ramp).
3. Poi **`svi_smoketest.py --create --unique`** → l'alert deve comparire in
   `queue_3264317`.
4. Ad alert creato: abilitare `SVI_SEND_ENRICHMENT=true` (poi scenario/contributing)
   per portare AMI/FATF/motivazione ed evidenze nell'evento.
5. **Off-ramp per lo schema documento Data Hub** (se serve creare il `Soggetto` e
   `--create-entity` non converge): catturare la request reale dalla **UI**
   (F12 → Network creando un record) e replicarla 1:1. Il formato "alerting data
   flat" **non** è più un'incognita: fornito dall'SVI Admin e implementato.

> Nota: dalla sessione Claude l'egress verso `*.race.sas.com` è **bloccato dalla
> policy di rete**, quindi tutte le chiamate live si eseguono e si verificano dalla
> macchina che raggiunge Viya.
