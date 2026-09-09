# SVI — attivazione LIVE (runbook)

Guida operativa per passare `svi-publisher` da `mock` a **live** contro un
ambiente SAS Viya / Visual Investigator reale. Il design del publisher (payload,
auth, retry, idempotenza) è in [`SVI_INTEGRATION.md`](SVI_INTEGRATION.md); qui i
passi concreti di attivazione e verifica.

> **Importante — dove si esegue.** Le chiamate a Viya vanno fatte **dalla macchina
> dove gira l'app** (Docker Desktop). Dalla sessione Claude l'egress verso
> `*.engage.sas.com` è **bloccato dalla policy di rete** (403 sul CONNECT), quindi
> auth e smoke-test si eseguono **in locale**, non da qui.

Ambiente di riferimento di questo runbook:

```
VIYA_ENDPOINT = https://viya-ddw4ej7fub.engage.sas.com
```

(ricavato dalla URL di accesso `.../SASVisualInvestigator/index.html#/home` —
il base è tutto ciò che precede `/SASVisualInvestigator`.)

---

## Passo 1 — Ottenere un token

Le API SVI si autenticano via OAuth2 (`{VIYA}/SASLogon/oauth/token`). Con il
**solo login web** (nessun client OAuth registrato) hai due modi.

> **Ambiente con SSO SAML** (come questo: l'accesso passa da un IdP esterno).
> Conseguenze pratiche:
> - il login **utente/password via CLI fallisce** («bad user»): non esiste una
>   password locale in SASLogon, l'identità è federata dall'IdP → **non usare** la
>   via B con password;
> - per un **servizio** (svi-publisher) la scelta giusta è un client
>   **`client_credentials`** (via C): è il client stesso a identificarsi, **SAML non
>   è coinvolto**;
> - per i test **subito**, prendi il token dal **browser** (via A): lì il SAML è
>   già stato completato.

### A) Via lampo — token dal browser (zero installazioni, sei già loggato)

Sei già collegato a SVI nel browser: quel login **ha già un token**, basta copiarlo.

1. Nel browser, con SVI aperto e loggato, premi **F12** (DevTools) → scheda **Network/Rete**.
2. Clicca il filtro **Fetch/XHR** (così vedi solo le chiamate API, non immagini/CSS).
3. Ricarica la pagina (F5) o clicca qualcosa in SVI: si popolano le richieste.
4. Clicca **più richieste** verso il server (es. `svi-datahub`, `svi-alert`,
   `identities`, `folders`) → scheda **Headers / Intestazioni** → **Request Headers**.
5. Cerca la riga `authorization: Bearer eyJ...` e copia **tutto ciò che segue `Bearer `**
   (stringa lunghissima che inizia con `eyJ`).

Se non trovi `authorization` su nessuna richiesta:
- prova **Application/Applicazione → Storage → Local/Session Storage**: cerca una
  chiave con un valore `eyJ...`;
- se davvero non c'è alcun bearer (la SPA usa **solo cookie di sessione**), la via
  browser non fa al caso tuo → passa alla **via C** (client `client_credentials`).

6. Incolla il token nel `.env` (modalità `token`):

```dotenv
SVI_MODE=live
VIYA_ENDPOINT=https://viya-ddw4ej7fub.engage.sas.com
SVI_AUTH_MODE=token
SAS_BEARER_TOKEN=eyJ...        # il token copiato dal browser
```

> Zero installazioni. Il token **scade** (qualche ora): perfetto per auth +
> discovery + primi test. Per il pilota non presidiato → via C.

### B) Via CLI — `sas-viya` (token, nessun client da registrare)

La CLI ufficiale `sas-viya` (un singolo eseguibile scaricabile da SAS: su Windows
`sas-viya.exe`) usa un client OAuth **già integrato**. Da un terminale della **tua
macchina** (PowerShell su Windows), nella cartella dove hai messo l'eseguibile:

```powershell
.\sas-viya.exe profile init     # Service Endpoint: https://viya-ddw4ej7fub.engage.sas.com
.\sas-viya.exe auth login       # utente/password del login web
# il token finisce in ~/.sas/credentials.json → campo "access-token"
```

(Se aggiungi `sas-viya.exe` al PATH, lo lanci da qualsiasi cartella senza `.\`.)
Copia quell'`access-token` nel `.env` con `SVI_AUTH_MODE=token` (come nel blocco A).

```dotenv
SVI_MODE=live
VIYA_ENDPOINT=https://viya-ddw4ej7fub.engage.sas.com
SVI_AUTH_MODE=token
SAS_BEARER_TOKEN=<incolla qui l'access-token>
```

> Il token **scade** (tipicamente qualche ora): perfetto per sbloccare subito
> auth, discovery del modello dati e i primi test con lo smoke-test. Per il pilota
> non presidiato passa alla via B.

### C) Via robusta (consigliata per il pilota) — client registrato — `client_credentials` o `password`

Un client dedicato dà token rinnovabili senza login interattivo. Ti servono
`client_id` + `client_secret`. **In ambiente SAML usa il grant
`client_credentials`**: il client è un'identità di servizio, indipendente
dall'IdP (nessun SAML, nessun utente). Registrazione tipica (richiede il *consul
token* di amministrazione dell'ambiente):

```bash
VIYA=https://viya-ddw4ej7fub.engage.sas.com
# 1) token di registrazione dal consul token (solo admin)
REG=$(curl -sk "$VIYA/SASLogon/oauth/clients/consul?callback=false&serviceId=adverse-media" \
      -X POST -H "X-Consul-Token: <CONSUL_TOKEN>" | jq -r .access_token)
# 2) crea il client
curl -sk "$VIYA/SASLogon/oauth/clients" -H "Authorization: Bearer $REG" \
  -H "Content-Type: application/json" -d '{
    "client_id": "adverse-media",
    "client_secret": "<UN_SECRET_FORTE>",
    "scope": ["openid"],
    "authorized_grant_types": ["password","client_credentials","refresh_token"],
    "authorities": ["uaa.none"],
    "access_token_validity": 43200
  }'
```

- `client_credentials` → il servizio agisce con l'identità del client (serve che
  il client abbia i diritti sugli oggetti SVI).
- `password` → il servizio agisce come un **utente** SVI (`SAS_USERNAME`/`SAS_PASSWORD`).
  ⚠ **Non utilizzabile con SSO SAML** (nessuna password locale): usa `client_credentials`.

Se non puoi registrare il client tu (serve il *consul token* o un client con
`clients.write`, tipicamente in mano all'**amministratore** dell'ambiente Engage),
chiedi all'admin SAS di crearlo e fartelo avere: passagli la specifica del blocco
qui sopra (`client_id: adverse-media`, grant `client_credentials`/`password`).

> Su SAS Viya **Engage** la registrazione client è dell'amministratore
> dell'ambiente. Nel frattempo le **vie A/B** (token) ti sbloccano con il solo
> login web.

---

## Passo 2 — Nomi del modello dati SVI

SVI è guidato da un **data model configurato**: il publisher scrive un *documento*
di un certo **tipo oggetto** e un *alert* di un certo **tipo/coda**. Questi nomi
sono specifici del tuo ambiente. Come ottenerli:

- da **SAS Visual Investigator → amministrazione / Environment Manager** (definizioni
  del data model: object/document types, alert types, code); oppure
- **automaticamente** con lo smoke-test (Passo 4): la fase di *discovery* elenca i
  tipi documento e le code che l'API restituisce.

Ti servono per:

```
SVI_OBJECT_TYPE=<tipo documento/record nel Data Hub>
SVI_ALERT_TYPE=<tipo alert>
SVI_QUEUE=<coda di destinazione, es. I livello>
SVI_EXTERNAL_ID_ATTR=<attributo usato per la dedup, default externalId>
```

---

## Passo 3 — `.env` (solo in locale, mai committato)

```dotenv
SVI_MODE=live
VIYA_ENDPOINT=https://viya-ddw4ej7fub.engage.sas.com
# base URL derivati da VIYA_ENDPOINT (override solo se il tuo routing differisce)
SVI_DATAHUB_BASE=
SVI_ALERTS_BASE=

# --- Auth (SASLogon) ---
SVI_AUTH_MODE=oauth
SAS_OAUTH_GRANT=client_credentials      # oppure: password
SAS_CLIENT_ID=adverse-media
SAS_CLIENT_SECRET=<il secret del client>
# solo se SAS_OAUTH_GRANT=password:
SAS_USERNAME=<utente SVI>
SAS_PASSWORD=<password>

# --- Modello dati (dal Passo 2) ---
SVI_OBJECT_TYPE=adverse_media_alert
SVI_ALERT_TYPE=AdverseMediaAlert
SVI_QUEUE=screening-primo-livello
SVI_EXTERNAL_ID_ATTR=externalId
```

> I segreti (`SAS_CLIENT_SECRET`, `SAS_PASSWORD`) vivono **solo** nel `.env`
> locale, che è escluso dal versionamento. Non incollarli in chat né committarli.

---

## Passo 4 — Smoke-test (in locale)

Dalla **root del repo**, con il `.env` valorizzato. Modo consigliato — nel
**container** (ha già Python e le dipendenze; legge il `.env` via `env_file`):

```bash
# dry-run: auth + discovery + payload stampato (nessuna scrittura)
docker compose -f docker-compose.dev.yml run --build --rm svi-publisher \
  python scripts/svi_smoketest.py

# scrive davvero 1 documento + 1 alert di test
docker compose -f docker-compose.dev.yml run --build --rm svi-publisher \
  python scripts/svi_smoketest.py --create
```

In alternativa, sull'host se hai Python: `pip install httpx pydantic pydantic-settings`
poi `python services/svi-publisher/scripts/svi_smoketest.py`.

Lo script:

1. **AUTH** — ottiene un token dal grant configurato (fallisce subito se il client
   o le credenziali non vanno: è il primo problema da risolvere);
2. **DISCOVERY** — sonda in sola lettura `svi-datahub` / `svi-alert` e prova a
   elencare **tipi documento / code** → sono i valori da mettere nel `.env` (Passo 2)
   e confermano i path reali degli endpoint;
3. **PAYLOAD** — stampa il documento + alert mappati; con `--create` li invia.

Non stampa mai token/segreti; le GET di discovery sono in sola lettura.

> Se una POST viene rifiutata per il `Content-Type`, l'ambiente vuole un media
> type versionato SAS (`application/vnd.sas...`): riportami la risposta e lo
> parametrizziamo.

---

## Passo 5 — Go-live

1. `SVI_MODE=live` nel `.env`;
2. riavvia il servizio: `docker compose -f docker-compose.dev.yml up -d --build svi-publisher`;
3. verifica salute: `curl localhost:8090/healthz` → `{"mode":"live","auth":"oauth"}`;
4. avvia uno screening reale dalla console; l'alert deve comparire in **SVI** con
   **evidenze + motivazione**;
5. controlla l'**idempotenza**: ripubblicare lo stesso screening non crea duplicati
   (stesso `externalId`, risposta `deduplicated: true`).

Retry con backoff e idempotenza sono già attivi (vedi `SVI_INTEGRATION.md`).

---

## Checklist

- [ ] Client OAuth registrato (`client_id` + `client_secret`) — o password grant con utente di servizio;
- [ ] token ottenuto dallo smoke-test (Passo 4.1);
- [ ] tipi documento/alert e coda confermati e messi nel `.env` (Passo 2);
- [ ] `--create` crea documento+alert; l'alert compare in SVI con evidenze;
- [ ] idempotenza verificata; poi `SVI_MODE=live` e screening reale.
