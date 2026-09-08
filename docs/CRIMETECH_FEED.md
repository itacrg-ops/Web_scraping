# Feed di rischio strutturato — Crime&tech (B9)

> Stato: **scaffolding pronto-da-collegare, default OFF.** Il codice è in
> `services/risk-gateway`; nessuna chiamata all'API reale avviene finché non si
> valorizzano chiave + spec + flag `CRIMETECH_LIVE`, e comunque l'egress verso
> `api.crimetech.app` è oggi bloccato dal proxy dell'ambiente.

## Cos'è (e cosa non è)

Crime&tech (spin-off di **Transcrime / Università Cattolica**, IT/UE) fornisce
**indicatori di rischio AML/CFT validati** su entità e persone: per ciascun
soggetto un insieme di indicatori **per tipo di reato**, con **rating
esplicabile**, riconciliazione delle entità e la **rete di connessioni**.

Non è un motore di web search: è una fonte **per identità**. Per questo **non
sostituisce** l'adverse media, lo **complementa**:

| | Adverse media (search-gateway) | Feed di rischio (risk-gateway) |
|---|---|---|
| Input | nome/qualificatori | **identità risolta** (entity_id) |
| Output | articoli (URL, testo) | indicatori + connessioni (strutturati) |
| Quando | discovery articoli | **dopo** l'Entity Resolution |
| PII verso terzi | redatte (B1/B1.1) | **identità reale inviata** (non redigibile) |

## Architettura

Il `risk-gateway` è il **punto unico di egress** verso i provider di rischio,
analogo a `search-gateway` (motori) e `llm-gateway` (Azure): concentra auth,
rate-limit e mappatura provider→dominio; il worker parla solo HTTP interno.

```
Entity Resolution (gate)
        │  soggetto RISOLTO
        ▼
worker: assess_risk_feed ──POST /v1/risk──► risk-gateway
                                              │
                                              ├─ RISK_PROVIDER="" → available:false (default)
                                              ├─ "mock"           → fixture locale
                                              └─ "crimetech"      → client stub:
                                                    1) reconcile soggetto → entity_id   (spec pending)
                                                    2) GET …/risk-indicators/{entity_id}/connections
                                                    3) normalize → mapping
        ▼
mapping: indicatori → FATF + severità ; connessioni a rischio → driver + evidenza
        ▼
workflow: unisce categorie/severità alla classificazione media → AMI ; driver in testa all'alert
```

Endpoint documentato di riferimento:

```
GET /dataset/{dataset_id}/risk-indicators/{entity_id}/connections
```

## Mappatura sul dominio

`services/risk-gateway/app/mapping.py` (funzioni **pure**, testate):

- **tipo di reato → categoria FATF** con le **stesse etichette** del classificatore
  media (`Corruption & Bribery`, `Fraud & Financial Crime`, `Money Laundering`,
  `Organized Crime`, `Terrorist Financing`, + `Sanctions & Embargoes`,
  `Environmental Crime`), così le categorie del feed e degli articoli si
  **fondono senza duplicati**;
- **rating → severità** (`alta|media|bassa`); la severità aggregata = **massimo**
  tra media e feed, quindi un riscontro dal feed **alza l'AMI anche quando gli
  articoli tacciono**;
- **connessioni a rischio → driver** esplicabili + **evidenza strutturata**
  (`tipo: connessione`, entità, relazione, categoria FATF) — segnali di rete che
  la ricerca testuale non vede.

## Configurazione (`.env`)

```dotenv
RISK_PROVIDER=            # ""=OFF (default) | mock | crimetech
CRIMETECH_BASE_URL=https://api.crimetech.app
CRIMETECH_DATASET_ID=    # path param {dataset_id}, fornito dal provider
CRIMETECH_API_KEY=       # MAI nel repo; solo via .env
CRIMETECH_LIVE=false     # guardia hard: live solo se true E chiave presente
```

`RISK_PROVIDER` è la **fonte di verità unica** per gateway e worker (stesso
`.env`): se vuoto, il worker non chiama nemmeno il gateway.

### Prova offline (senza rete)

`RISK_PROVIDER=mock` usa una fixture dimostrativa: si vede l'intera catena
(mappatura, unione FATF/severità, driver, evidenza) senza toccare l'API reale.

## Compliance — prerequisiti all'attivazione `crimetech`

La redazione PII **non è applicabile**: interrogare il feed richiede di inviare
l'**identità reale** del soggetto a un processore esterno. Prima di attivare:

1. **Spec OpenAPI** ufficiale (endpoint di reconcile + schema dei campi);
2. **Chiave API** e **licenza/DPA** (contratto di trattamento dati);
3. **DPIA aggiornata**: è un nuovo trasferimento di dati personali verso terzi;
4. **Base giuridica** del trattamento e minimizzazione (solo soggetti pertinenti
   all'istruttoria, non screening massivo).

Le due guardie `CRIMETECH_LIVE` + `CRIMETECH_API_KEY` bloccano ogni egress finché
non sono entrambe valorizzate.

## Cosa manca per collegarlo (checklist)

- [ ] `crimetech._resolve_entity_id`: implementare la riconciliazione
      soggetto→`entity_id` sull'endpoint reale (oggi ritorna `None` = stub);
- [ ] `crimetech._normalize_connections_response`: confermare i nomi dei campi
      sull'OpenAPI (oggi provvisori, isolati in un solo punto);
- [ ] DPIA/DPA firmati; valorizzare `CRIMETECH_*` in `.env` e `RISK_PROVIDER=crimetech`;
- [ ] test su una risposta reale d'esempio (oggi: fixture `mock`).
