# Onboarding di un nuovo ambiente/dominio SAS VI

Come ricavare i valori di configurazione e attivare la pubblicazione, passo per passo.

## 1. Ottenere un token
A seconda dell'ambiente:
- **Client registrato** (consigliato prod): `SVI_AUTH_MODE=oauth`, `SAS_OAUTH_GRANT=client_credentials`, `SAS_CLIENT_ID/SECRET`.
- **Demo con auth locale**: client integrato `sas.ec` (secret vuoto) + `SAS_OAUTH_GRANT=password` + `SAS_USERNAME/PASSWORD`.
- **Test rapido**: `SVI_AUTH_MODE=token` + `SAS_BEARER_TOKEN` (bearer dal browser/`sas-viya auth`; scade).

Se il login web è SAML/SSO, **non** esiste una password locale per la CLI: usa client registrato o il token dal browser.

## 2. Scoprire i valori del dominio
Con `.env` che ha almeno `VIYA_ENDPOINT` + auth valida:

```
python scripts/svi_inspect.py
```

Dall'output ricava per il `.env`:
- **`SVI_QUEUE`** = una coda con `acceptManualAlerts=true` (righe `queues`).
- **`SVI_ENTITY_TYPE`** = l'entity type del dominio (es. `Soggetto`).
- **`SVI_ALERT_TYPE_CODE`** = un `code` valido tra gli `alertTypes` (obbligatorio).
- (informativo) il `domainId` e la `strategy` attiva.

La sezione "ALERT DI ESEMPIO" mostra com'è fatto un alert reale e se l'ambiente
memorizza l'`enrichmentJson`.

## 3. TLS
- Demo self-signed → `SVI_VERIFY_TLS=false` (equivale a `curl -k`, **solo** demo).
- Meglio: `SVI_CA_BUNDLE` = path al certificato/CA del server (verifica attiva).

## 4. Testare il payload
```
python scripts/svi_smoketest.py                 # dry-run: stampa l'envelope
python scripts/svi_smoketest.py --create --unique   # crea un alert di prova
python scripts/svi_smoketest.py --diagnose      # se qualcosa non va, isola il campo
```
Verifica che l'alert compaia nella coda `SVI_QUEUE`.

## 5. Collegare l'app
- Scrivi l'**adapter** (vedi `templates/adapter_template.py`): dominio app → `SviAlert`.
- Metti `SVI_MODE=live` nel servizio (non solo nello smoke-test) e **ricrea** il
  processo/container (l'env si legge all'avvio).
- L'idempotenza è automatica: stessa `business_key` → nessun duplicato.

## 6. (Opzionale) Mostrare l'enrichment sull'alert
I campi `enrichment` sono **memorizzati** in `enrichmentJson`, ma la loro
**visualizzazione** è configurazione di pagina lato SVI:
- apri **Manage Investigate and Search → Page Builder / Manage Pages** per il dominio;
- nella scheda alert (e/o colonne Alert Grid) aggiungi campi legati a
  `enrichmentJson.<chiave>` (es. `enrichmentJson.risk_level`);
- salva/pubblica.

La motivazione completa è comunque già leggibile nel campo core `alertTriggerText`.
Scorciatoia: se un campo enrichment è già mostrato per un altro dominio (es. un
`categoria_*`), replica quella configurazione di pagina per i tuoi campi.

## 7. Produzione (hardening)
- Auth: da `password`/`sas.ec` a un **client registrato** con `client_credentials`.
- TLS: riattivare la verifica (`SVI_CA_BUNDLE`).
- Idempotenza: valutare una cache condivisa (Redis/outbox) al posto di quella in-process
  per dedup cross-restart e multi-replica.
