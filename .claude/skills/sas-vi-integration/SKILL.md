---
name: sas-vi-integration
description: >-
  Integrate an application with SAS Visual Investigator (SVI) on SAS Viya — authenticate via
  SASLogon, build the flat "alerting event" envelope, and publish alerts (with score, motivation
  and enrichment) into an SVI queue idempotently. Use this whenever the user is building or wiring
  an app that needs to push alerts, cases, risk signals or entities to SAS Visual Investigator /
  SVI / SAS Viya alerting — even if they don't name the envelope. Trigger on mentions of svi-alert,
  svi-datahub, alertingEvents, "alerting event", enrichmentJson, actionableEntity, SASLogon/Viya
  auth for alerting, onboarding a new SVI domain (discover queues/strategies/alertTypes), or
  debugging SVI publish errors (tdc.bad.request, errorCode 1008, DH5104, 415 media type, alerts 405).
  Provides a reusable svi_core Python library (auth, envelope, retry + 1008-idempotency), an adapter
  template, and diagnostic scripts (smoke-test, environment inspector).
---

# SAS Visual Investigator (SVI) integration

Asset riutilizzabile per far pubblicare a una nuova applicazione i propri alert in **SAS
Visual Investigator** su SAS Viya. Incapsula la conoscenza specifica di SVI (auth,
formato payload, robustezza) in una libreria generica **`svi_core`**, così ogni app scrive
solo un piccolo **adapter** dal proprio dominio al contratto canonico `SviAlert`.

Questa conoscenza è **reverse-engineered sul campo**: usala per non ripetere gli errori
(500/1008/DH5104) e per arrivare all'alert in coda velocemente.

## Quando usarla
Quando devi integrare un'app con SVI: pubblicare alert/segnalazioni, autenticarti a Viya
per l'alerting, costruire un "alerting event", onboardare un nuovo dominio SVI, o
diagnosticare errori di pubblicazione. Vale anche se l'utente non nomina l'envelope.

## Concetti chiave (leggi prima di scrivere codice)
- L'alert si crea con un **alerting event**: `POST /svi-alert/alertingEvents`, body =
  **envelope** `{"jsonLayout":"flat","alertingEvents":[…]}`, media type versionato. **Non**
  con `POST /svi-alert/alerts` (405). Dettagli: [`references/envelope.md`](references/envelope.md).
- `alertTypeCode` è **obbligatorio**; `recommendedQueueId` è opzionale; l'entità **non**
  deve pre-esistere; l'evento non porta `domainId`.
- Idempotenza: `alertingEventId` deterministico dalla `business_key`; SVI rifiuta i
  duplicati con `errorCode 1008` → trattato come successo idempotente, non errore.
- `score` e `alertTriggerText` sono campi core **sempre mostrati** (metti la motivazione
  in `alertTriggerText`). L'`enrichment` è memorizzato in `enrichmentJson` ma **mostrarlo
  è config di pagina** (Page Builder), non definizione di attributi.

## Come integrare una nuova app (workflow)

1. **Copia la libreria e i template nel servizio.** Porta `assets/svi_core/` (la libreria)
   e, come punto di partenza, `assets/templates/adapter_template.py` e
   `assets/templates/.env.svi.example` (rinominalo `.env`). Copia anche
   `assets/scripts/` accanto a `svi_core` per test/onboarding. Dipendenze:
   `httpx`, `pydantic-settings` (vedi `svi_core/requirements.txt`).

2. **Scrivi l'adapter** (l'unica parte app-specific). Mappa l'oggetto di dominio su
   `SviAlert` e chiama `svi_core.publish`:
   ```python
   from svi_core import SviAlert, publish
   alert = SviAlert(
       business_key=obj.case_id,          # id STABILE (idempotenza)
       entity_id=obj.tax_id or obj.case_id,
       entity_label=obj.name,             # nome leggibile in coda
       score=obj.risk_score,
       trigger_text=obj.explanation,      # motivazione (mostrata di default)
       enrichment={"risk_level": obj.level, "category": obj.category},
   )
   res = await publish(alert)             # {svi_alert_id, deduplicated}
   ```
   Scegli una `business_key` stabile per caso/screening: stessa chiave → nessun duplicato.

3. **Onboarda l'ambiente**: ricava i valori del `.env` con
   `python scripts/svi_inspect.py` (coda con `acceptManualAlerts=true` →
   `SVI_QUEUE`; entity type → `SVI_ENTITY_TYPE`; un `alertTypes.code` valido →
   `SVI_ALERT_TYPE_CODE`). Guida completa: [`references/onboarding.md`](references/onboarding.md).

4. **Testa** senza toccare l'app: `python scripts/svi_smoketest.py` (dry-run) →
   `--create --unique` (crea un alert di prova) → verifica in coda. Se qualcosa fallisce,
   `--diagnose` isola il campo e [`references/troubleshooting.md`](references/troubleshooting.md)
   dà causa/rimedio.

5. **Vai live**: `SVI_MODE=live` nel servizio (non solo nello smoke-test) e **ricrea** il
   processo/container (l'env si legge all'avvio). In `mock` (default) `publish` ritorna id
   `svi-mock-…` senza chiamare Viya — comodo per sviluppo/test.

## Struttura dell'asset
```
assets/svi_core/         # libreria generica (NON toccare per app-specific):
  models.py    # SviAlert (contratto canonico)
  config.py    # SviConfig (env SVI_/SAS_/VIYA_)
  auth.py      # SASLogon (oauth/token/broker)
  envelope.py  # build_alerting_payload (envelope flat)
  client.py    # publish() : mock/live, retry, 1008-idempotenza
  test_svi_core.py   # self-test offline (python test_svi_core.py)
assets/templates/        # .env.svi.example, adapter_template.py (copia e adatta)
assets/scripts/          # svi_smoketest.py (test), svi_inspect.py (onboarding/diagnosi)
references/              # envelope.md, troubleshooting.md, onboarding.md
```

## Regole importanti
- **Non riscrivere `svi_core`** per esigenze di dominio: mettile nell'adapter. Se manca
  qualcosa di *generico* (es. un nuovo campo dell'envelope), estendi `svi_core` e aggiorna
  il self-test.
- **Segreti solo in `.env`**, mai nel codice/repo. In produzione: `client_credentials` +
  verifica TLS attiva (`SVI_CA_BUNDLE`).
- La libreria è validata offline da `assets/svi_core/test_svi_core.py`: eseguilo dopo
  ogni modifica a `svi_core`.
