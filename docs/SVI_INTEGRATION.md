# Integrazione SAS Visual Investigator (SVI) — configurazione e payload (B2)

> Stato: **publisher reale implementato**, `SVI_MODE=mock` di default. Il ramo
> `live` costruisce auth + payload + retry + idempotenza; **non ancora
> esercitato** su una Viya reale (nessun ambiente disponibile e egress verso Viya
> bloccato dal proxy). Le parti pure (mapping, business key, auth builder) sono
> testate offline (7/7).

## Architettura

`svi-publisher` è l'**anti-corruption layer** verso SVI: il worker gli invia un
alert canonico; il servizio traduce e pubblica. Tutta la conoscenza SVI è
confinata qui (payload in `app/mapping.py`, auth in `app/auth.py`, orchestrazione
in `app/svi_client.py`).

```
worker (publish_svi) ──POST /publish/alert──► svi-publisher
                                                │  mock → id fittizio (default)
                                                │  live ↓
                                                ├─ auth: OAuth2 SASLogon | broker
                                                ├─ POST {viya}/svi-datahub/documents   (record)
                                                └─ POST {viya}/svi-alert/alerts         (alert → coda)
```

Endpoint di riferimento (SAS Viya):
- **Auth**: `POST {VIYA_ENDPOINT}/SASLogon/oauth/token` → Bearer token
- **Data Hub**: `{VIYA_ENDPOINT}/svi-datahub/*` (documents, links)
- **Alert**: `{VIYA_ENDPOINT}/svi-alert/*` (create/update/retrieve/delete)

## Payload (mapping)

Dall'alert interno si producono **due** oggetti SVI. I nomi di tipo/coda/attributo
esterno vengono dalla config (deployment-specific), non sono cablati.

### 1) Documento nel Data Hub (`POST /svi-datahub/documents`)

```json
{
  "objectType": "adverse_media_alert",
  "externalId": "ams-SCR-123",
  "attributes": {
    "subjectName": "ACME Costruzioni S.r.l.",
    "subjectType": "persona_giuridica",
    "taxId": "00743110157",
    "cupCodes": ["E51B21000000001"],
    "amiScore": 82,
    "riskLevel": "ALTO",
    "fatfCategories": ["Corruption & Bribery", "Money Laundering"],
    "disposition": "ESCALATION_I_LIVELLO",
    "rationale": "Categorie FATF: … • Corroborazione: … • AMI = 82",
    "evidence": [
      {"url": "https://…", "source": "testata.it", "title": "…", "date": "2026-01-02",
       "snippet": "…", "contentHash": "…", "credibility": "alta",
       "fetchTs": "2026-01-02T10:00:00Z", "warcKey": "…"}
    ],
    "sourceSystem": "adverse-media-screening",
    "externalId": "ams-SCR-123"
  }
}
```

- **motivazione** → `rationale` (i driver dell'AMI in un unico testo);
- **evidenze** → array `evidence` (URL, testata, hash, credibilità, chiave WARC).

### 2) Alert (`POST /svi-alert/alerts`)

```json
{
  "alertType": "AdverseMediaAlert",
  "queue": "screening-primo-livello",
  "status": "NEW",
  "score": 82,
  "riskLevel": "ALTO",
  "subject": "ACME Costruzioni S.r.l.",
  "categories": ["Corruption & Bribery", "Money Laundering"],
  "summary": "AMI 82 (ALTO) — ACME Costruzioni S.r.l.",
  "disposition": "ESCALATION_I_LIVELLO",
  "sourceSystem": "adverse-media-screening",
  "externalId": "ams-SCR-123",
  "documentId": "<id del documento creato al passo 1>"
}
```

## Idempotenza

**Business key** = `ams-{screening_id}` (in mancanza, hash del contenuto canonico).
Va sull'attributo esterno `externalId` (nome configurabile) **e** in una cache
in-process `business_key → id`: ripubblicare lo stesso screening (es. retry di
Temporal) restituisce lo **stesso** id, `deduplicated: true`, senza creare
duplicati. In produzione la cache diventa un **outbox/Redis** condiviso; l'
`externalId` consente anche la dedup lato SVI se il data model lo impone univoco.

## Robustezza

Retry con backoff esponenziale (`SVI_MAX_RETRIES`, `SVI_RETRY_BACKOFF`) sugli
errori transitori (timeout, connessione, `429/5xx`); il resto degli errori
propaga (l'activity `publish_svi` ha il proprio retry Temporal a monte).

## Configurazione (`.env`)

```dotenv
SVI_MODE=live
VIYA_ENDPOINT=https://viya.example.org
# base URL: default {VIYA_ENDPOINT}/svi-datahub e /svi-alert (override se serve)
SVI_DATAHUB_BASE=
SVI_ALERTS_BASE=

# Auth: oauth (SASLogon) | broker (sidecar). Segreti SOLO in .env.
SVI_AUTH_MODE=oauth
SAS_OAUTH_GRANT=client_credentials     # o password
SAS_CLIENT_ID=…
SAS_CLIENT_SECRET=…
# SAS_USERNAME/SAS_PASSWORD solo per grant=password

# Data model SVI (allinea ai tipi definiti nel cliente)
SVI_OBJECT_TYPE=adverse_media_alert
SVI_ALERT_TYPE=AdverseMediaAlert
SVI_QUEUE=screening-primo-livello
SVI_EXTERNAL_ID_ATTR=externalId
```

## Prova in locale (senza Viya)

`SVI_MODE=mock` (default): la pubblicazione logga e restituisce id deterministici
(`svi-mock-…`), con la stessa idempotenza. La console mostra l'`svi_alert_id`
sull'alert. Utile per validare la pipeline end-to-end senza ambiente SAS.

> **Attivazione passo-passo:** [`SVI_GOLIVE.md`](SVI_GOLIVE.md) — runbook con
> registrazione client OAuth, discovery del modello dati, `.env` e smoke-test.

## Cosa manca per l'attivazione live (checklist)

- [ ] Ambiente **Viya/SVI** e **data model** configurato (tipi oggetto/alert/
      coda); allineare `SVI_OBJECT_TYPE/ALERT_TYPE/QUEUE/EXTERNAL_ID_ATTR`;
- [ ] credenziali OAuth (client o utente di servizio) in `.env`;
- [ ] verificare i **path/campi reali** di `svi-datahub/documents` e
      `svi-alert/alerts` sulla versione SVI del cliente (l'anti-corruption layer
      isola le eventuali differenze in `mapping.py`);
- [ ] test su un alert reale: compare in SVI con **evidenze + motivazione**;
      verifica retry e idempotenza.

## Riferimenti

- [Getting started with the REST APIs of Visual Investigator (SAS Communities)](https://communities.sas.com/t5/SAS-Communities-Library/Getting-started-with-the-REST-APIs-of-Visual-Investigator/ta-p/885177)
- [Visual Investigator Alerts API (SAS Developer)](https://developer.sas.com/rest-apis/svi-alert)
- [SAS Visual Investigator: Data REST API Reference](https://documentation.sas.com/api/collections/vicdc/v_033/docsets/vidhapi/content/vidhapi.pdf)
- [REST APIs — SAS Developer Portal](https://developer.sas.com/rest-apis)

> Nota: gli endpoint `svi-datahub`/`svi-alert` e i tipi oggetto/alert sono
> **specifici della versione e del data model** del deployment; i nomi qui sono
> default sensati, allineabili da `.env` senza modificare il codice.
