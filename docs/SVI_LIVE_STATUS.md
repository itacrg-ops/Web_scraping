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
  `application/vnd.sas.investigation.triage.alerting.data.flat+json;version=1`,
  **body = oggetto singolo** (l'array viene rifiutato al parsing).
- **Schema alerting event (flat)** ricavato dall'ambiente: `domainId`,
  `actionableEntityType/Id/Label`, `score`, `recommendedQueueId`, `alertTypeCode`,
  `alertOriginCode`, `enrichment` (mappa string→string), `alertingEventId`.

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
```

## Blocchi aperti (config SVI, **non** codice)

1. **Alerting event → HTTP 500 `tdc.bad.request` generico**, identico **anche a
   body vuoto**. Quindi non è un campo del payload, ma un **prerequisito**:
   - la **strategia** del dominio Adverse Media dev'essere **ATTIVA/deployata**
     (una strategia `INACTIVE` non elabora gli alerting event — nell'ambiente la
     strategia PI di esempio era `INACTIVE`); **e/o**
   - l'**entità `Soggetto`** referenziata (`actionableEntityId`) deve **esistere**
     come record nel Data Hub.
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

- `services/svi-publisher/scripts/svi_smoketest.py` — auth + discovery + `--create`
  (crea l'alerting event dell'alert di prova).
- `services/svi-publisher/scripts/svi_admin.py` — discovery admin (domini/strategie/
  code/eventi); `--probe` (rivela media type/campi con POST vuoto, non crea);
  `--create-entity` (prova più nomi campo per creare il record `Soggetto`).

Esecuzione (dalla macchina che raggiunge Viya):
```powershell
docker compose -f docker-compose.dev.yml run --build --rm svi-publisher python scripts/svi_admin.py --create-entity
docker compose -f docker-compose.dev.yml run --build --rm svi-publisher python scripts/svi_smoketest.py --create
```

## Prossimi passi

1. **Attivare/deployare la strategia** Adverse Media (probabile causa reale del
   blocco alert). Verificare in *Alerts → Domains → strategia* che lo stato non sia
   `INACTIVE`.
2. **Creare il record `Soggetto`**: individuare campo tipo + attributi
   (`svi_admin.py --create-entity`) e creare l'entità `00743110157`.
3. Rieseguire `svi_smoketest.py --create` → l'alert deve comparire in
   `queue_3264317`.
4. **Off-ramp definitivo** se il reverse-engineering non converge: catturare i
   payload reali dalla **UI** (F12 → Network creando un record e un alert manuale)
   e replicarli 1:1, oppure farsi passare dal **referente SAS** il formato
   "alerting data flat" e lo schema del documento Data Hub.
5. A creazione OK: `SVI_SEND_ENRICHMENT=true` per portare AMI/FATF/motivazione
   nell'`enrichment` dell'evento.

> Nota: dalla sessione Claude l'egress verso `*.race.sas.com` è **bloccato dalla
> policy di rete**, quindi tutte le chiamate live si eseguono e si verificano dalla
> macchina che raggiunge Viya.
