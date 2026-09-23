# Envelope "alerting event" SAS VI — specifica

Come si crea un alert in SAS Visual Investigator via API, con i dettagli che fanno la
differenza (ricavati sul campo).

## Endpoint e media type
- Gli alert **non** si creano con `POST /svi-alert/alerts` → `405` (sola lettura).
- Si crea un **alerting event**: `POST /svi-alert/alertingEvents`.
- **Media type obbligatorio** (versionato, il suffisso è necessario):
  `application/vnd.sas.investigation.triage.alerting.data.flat+json;version=1`

## Il body è un ENVELOPE (non un oggetto singolo)
Deve avere il discriminatore `jsonLayout:"flat"` e sezioni ad **array**. Senza envelope,
SVI risponde `500 tdc.bad.request` (rifiuto di struttura, identico anche a body vuoto).

```json
{
  "jsonLayout": "flat",
  "alertingEvents": [
    {
      "alertingEventId": "<uuid deterministico dalla business key>",
      "actionableEntityType": "<entity type, es. Soggetto>",
      "actionableEntityId": "<id entità, es. CF/P.IVA>",
      "actionableEntityLabel": "<nome leggibile in coda>",
      "score": 82,
      "alertTypeCode": "<OBBLIGATORIO, es. strategy_default>",
      "recommendedQueueId": "<coda, opzionale>",
      "alertTriggerText": "<motivazione leggibile, mostrata di default>",
      "alertOriginCode": "<opzionale>"
    }
  ],
  "enrichment":          [ { "alertingEventId": "…", "<campo>": "<valore stringa>" } ],
  "scenarioFiredEvents": [ { "alertingEventId": "…", "scenarioName": "…", "score": 0 } ],
  "contributingObjects": [ { "alertingEventId": "…", "url": "…" } ]
}
```

## Regole confermate (dal `--diagnose`)
- **`alertTypeCode` è OBBLIGATORIO**: senza → `500 errorCode 1008`.
- **`recommendedQueueId` è OPZIONALE**: l'alert si crea anche senza (la strategia instrada).
- **L'entità NON deve pre-esistere** nel Data Hub: l'alert si crea comunque.
- L'evento **non** ha `domainId` (implicito nella coda/strategia).
- `enrichment` / `scenarioFiredEvents` / `contributingObjects` sono **opzionali** e ogni
  riga si collega all'evento tramite `alertingEventId`.

## Dove finiscono i dati sull'alert
- `score` → campo core dell'alert (`initialScore/currentScore/highScore`) — **sempre mostrato**.
- `alertTriggerText` → campo core — **sempre mostrato** (mettici la motivazione completa).
- `enrichment[]` → memorizzato sull'alert nel campo **`enrichmentJson`** (oggetto annidato).
  **È salvato ma non mostrato di default**: la visualizzazione è configurazione di pagina
  (Page Builder / colonne Alert Grid), non definizione di attributi. Vedi `onboarding.md`.

## Idempotenza
- `alertingEventId` deterministico (`uuid5` dalla `business_key`) → stessa business key,
  stesso id evento.
- SVI rifiuta i duplicati con `500 errorCode 1008` — **ma lo stesso codice 1008 vale anche
  per riferimenti non risolvibili** (dominio/coda/entityType/alertTypeCode assenti). È
  ambiguo: `svi_core` lo tratta come duplicato solo dopo un tentativo con **esito ambiguo**
  per la stessa chiave (timeout in lettura, connessione caduta, 500/502/504), altrimenti
  solleva `SviRejected` (l'alert non è creato da questa richiesta). `SVI_DEDUP_ON_1008=true`
  = ogni 1008 è duplicato. In ogni caso il 1008 non è transitorio e non viene ritentato.
