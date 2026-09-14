# SVI — attivazione live (as-built): **FUNZIONANTE end-to-end** ✅

> **STATO: LIVE OK.** Lo screening reale (pipeline Temporal → `svi-publisher` in
> `SVI_MODE=live`) crea l'alert in SAS Visual Investigator, con `SVI_SEND_ENRICHMENT=true`
> (AMI/FATF/motivazione nell'evento). Percorso completo verificato dall'utente.

Handoff dell'integrazione live verso SAS Visual Investigator: cosa è **validato**,
cosa resta opzionale e come è configurato. Ambiente di test: **SAS Viya RACE demo**
`https://azureuse030088.race.sas.com`. Runbook operativo: [`SVI_GOLIVE.md`](SVI_GOLIVE.md);
modello dominio: [`SVI_DOMAIN_ADVERSE_MEDIA.md`](SVI_DOMAIN_ADVERSE_MEDIA.md).

## Validato ✅

- **Auth**: OAuth SASLogon con client integrato **`sas.ec`** (secret vuoto), grant
  **password** (utente demo). Token ottenuto (scope amministrativi).
- **TLS**: certificato self-signed → `SVI_VERIFY_TLS=false` (solo demo).
- **Publisher**: `svi-publisher` config-driven; test unitari 10/10 (mapping envelope +
  idempotenza, incluso il ramo live 1008-duplicato).
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
- **ALERT CREATO — HTTP 201** ✅✅ — l'envelope produce l'alert (verificato con
  `svi_smoketest.py --diagnose`, variante `baseline` → `201 Created`). **L'integrazione
  live funziona end-to-end.**
- **Regole del payload ricavate dal `--diagnose`** (varianti con omissioni controllate):
  - **`alertTypeCode` è OBBLIGATORIO** — senza → `500 errorCode 1008`. `strategy_default`
    è un codice **valido** per questo dominio (baseline con esso → 201).
  - **`recommendedQueueId` è OPZIONALE** — 201 anche senza (lo teniamo per il routing).
  - **L'entità NON deve pre-esistere** — l'alert si crea anche senza aver caricato il
    record `Soggetto` nel Data Hub (chiude il blocco "creazione entità" come *requisito*).
- **`errorCode 1008` = duplicato / dato mancante** (NON struttura): con `alertTypeCode`
  valorizzato, un 1008 significa **alertingEventId già esistente** (stesso screening →
  id deterministico → SVI rifiuta i duplicati). Il publisher ora lo tratta come
  **idempotenza** (successo, `deduplicated=true`), mai come errore, e non lo ritenta.
- **Pipeline reale live** ✅ — `worker → svi-publisher (/publish/alert) → SVI`: lo screening
  end-to-end crea l'alert. Prerequisiti risolti: `SVI_MODE=live` onorato dal `.env`
  (rimosso l'override compose che forzava mock); `SVI_LOAD_ENTITY=false` (il documento
  Data Hub, opzionale e non ancora mappato, non blocca più l'alert).
- **Enrichment attivo** ✅ — `SVI_SEND_ENRICHMENT=true`: l'evento porta AMI, risk level,
  categorie FATF, disposition e motivazione (sezione `enrichment[]` collegata all'evento).
- **Osservabilità** — i log applicativi (`svi_publisher`) sono visibili sotto uvicorn e
  distinguono **CREATO vs DUPLICATO** (con score/coda/tipo/sezioni); il worker logga
  `id/mode/dedup`.

## Configurazione trovata nell'ambiente

| Cosa | Valore |
|---|---|
| Dominio "Adverse Media" | `domainId = d_42843825` |
| Entity type | `Soggetto` |
| Coda con `acceptManualAlerts=true` | `queue_3264317` (opzionale nell'evento) |
| Strategia | `strategy_36821163` (attiva — l'alert è stato creato) |
| Alert type code | `strategy_default` (obbligatorio, valido) |

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

## Blocchi risolti / non più bloccanti

1. **~~Alerting event → 1008~~** — **RISOLTO**. Il `--diagnose` ha dimostrato che
   `baseline` (envelope completo) → **201 Created**. Il 1008 dipendeva da:
   `alertTypeCode` mancante (obbligatorio) **o** `alertingEventId` duplicato (ora
   gestito come idempotenza dal publisher). `strategy_default`, `queue_3264317` e la
   strategia sono quindi validi/attivi.
2. **~~Creazione entità Soggetto come prerequisito~~** — **NON necessaria** per creare
   l'alert (baseline crea l'alert senza record `Soggetto`). Resta un *nice-to-have*
   solo se si vuole arricchire l'anagrafica nel Data Hub; il body di insert
   (`POST /svi-datahub/documents`, tipo via `objectTypeName`, campo `identificativo`/
   Name `CodiceFiscalePIVA`) non è ancora stato azzeccato (sempre `DH5104`) e andrebbe
   ricavato catturando la request reale della UI. **Fuori dal percorso critico.**

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
docker compose -f docker-compose.dev.yml run --build --rm svi-publisher python scripts/svi_smoketest.py --create --unique
docker compose -f docker-compose.dev.yml run --build --rm svi-publisher python scripts/svi_smoketest.py --diagnose
```

## Prossimi passi

1. **Verificare l'alert in coda**: aprire `queue_3264317` in SVI e controllare che
   l'alert `baseline`/`--create --unique` sia arrivato con lo score 82 e il testo.
2. **Arricchire l'evento**: abilitare in `.env` `SVI_SEND_ENRICHMENT=true` e rilanciare
   `--create --unique`; poi, se il dominio li accetta, `SVI_SEND_SCENARIO_EVENTS=true`
   e `SVI_SEND_CONTRIBUTING_OBJECTS=true` (AMI/FATF/motivazione + findings + evidenze).
   Se una sezione dà 1008, quella chiave non è mappata sul dominio → lasciarla off.
3. **Collegare la pipeline**: impostare `SVI_MODE=live` nel servizio (non solo nello
   smoke-test) così che gli alert reali dello screening vengano pubblicati. L'idempotenza
   è già gestita (stesso screening → stesso `alertingEventId`; il duplicato 1008 è
   trattato come dedup).
4. **Endur./sicurezza**: passare dal grant `password` demo a `client_credentials` con
   client registrato; riattivare la verifica TLS (`SVI_CA_BUNDLE` col cert del server).
5. *(Opzionale, fuori percorso critico)* schema del documento Data Hub per l'anagrafica
   `Soggetto`: ricavarlo catturando la request reale dalla **UI** (F12 → Network).
   ⚠ Nel servizio tenere **`SVI_LOAD_ENTITY=false`** (default): con `true` il publisher
   tenta prima `POST /svi-datahub/documents`, che oggi dà `400/DH5104` (schema non
   allineato). Il caricamento entità è comunque **non bloccante** (una sua failure
   logga un warning e prosegue con l'alert), ma con `false` si evita la chiamata inutile.

> Nota: dalla sessione Claude l'egress verso `*.race.sas.com` è **bloccato dalla
> policy di rete**, quindi tutte le chiamate live si eseguono e si verificano dalla
> macchina che raggiunge Viya.
