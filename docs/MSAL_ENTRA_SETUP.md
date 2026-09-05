# Autenticazione della console con Entra ID (MSAL)

Attiva il **SSO con Microsoft Entra ID** per la console di amministrazione
React e la protezione dell'API back-end. È **opzionale**: in locale l'auth è
disattivata (utente dev fittizio) e tutto gira senza Entra. Questa guida spiega
come accenderla — vale sia in locale (Docker Desktop) sia in produzione (Azure),
stesso codice, cambiano solo le variabili d'ambiente.

L'API è l'**unico confine di fiducia** verso la console (§3 del documento di
deployment): la SPA ottiene un token da Entra via MSAL, l'API lo valida
(firma JWKS RS256, audience, issuer) ed estrae i **ruoli applicativi** per l'RBAC.
La SPA non parla mai direttamente con DB / coda / LLM / SAS.

```
Utente ──login──▶ Entra ID ──access token (JWT)──▶ SPA (MSAL)
                                                      │  Authorization: Bearer <jwt>
                                                      ▼
                                                   API back-end ──valida firma/aud/iss──▶ RBAC (claim "roles")
```

## 1. Prerequisiti
- Un **tenant Entra ID** (lo stesso dell'account Azure usato per Foundry va bene).
- Diritti per creare **due App registration**: una per l'**API** (risorsa
  protetta) e una per la **SPA** (client pubblico). Tenere due app separate è la
  prassi consigliata per le SPA.
- `az` CLI oppure il portale Entra (*Microsoft Entra ID → App registrations*).

Annota il **Tenant ID** (GUID):
```bash
az account show --query tenantId -o tsv
```

## 2. App registration per l'**API** (risorsa protetta)
1. *App registrations → New registration*: nome es. `ams-api`, account
   *Single tenant*. Nessun redirect URI. Annota l'**Application (client) ID**
   → lo chiameremo `<api-client-id>`.
2. *Expose an API*:
   - Imposta l'**Application ID URI** (default `api://<api-client-id>`).
   - *Add a scope*: nome **`access_as_user`**, consenso *Admins and users*,
     abilitato. Lo scope completo sarà `api://<api-client-id>/access_as_user`.
3. *App roles* — definisci i ruoli applicativi (claim `roles` nel token),
   assegnabili a *Users/Groups*:
   | Display name    | Value            | Descrizione                       |
   |-----------------|------------------|-----------------------------------|
   | Amministratore  | `amministratore` | Configura fonti, avvia screening  |
   | Auditor         | `auditor`        | Sola lettura di alert/observability |
4. *Manifest*: verifica `"accessTokenAcceptedVersion": 2` (token v2, issuer
   `login.microsoftonline.com/<tenant>/v2.0`). Il codice accetta anche v1
   (`sts.windows.net`), ma v2 è la scelta pulita.
5. *Enterprise applications → <ams-api> → Users and groups*: assegna agli
   utenti i ruoli `amministratore` / `auditor`.

## 3. App registration per la **SPA** (console React)
1. *New registration*: nome es. `ams-console`, *Single tenant*. Annota il
   client id → `<spa-client-id>`.
2. *Authentication → Add a platform → **Single-page application***. Redirect URI:
   - locale: `http://localhost:5173`
   - produzione: l'URL pubblico della console (es. `https://ams.<dominio>`).
   Non servono "implicit grant" flag (MSAL usa Authorization Code + PKCE).
3. *API permissions → Add a permission → My APIs → `ams-api` →
   Delegated → `access_as_user`*, poi **Grant admin consent**.

## 4. Variabili d'ambiente
Popola il `.env` (vedi `.env.example`). L'**audience** deve combaciare *esattamente*
con il claim `aud` del token: con token v2 è il **client id dell'API** (`<api-client-id>`);
in alcune configurazioni è l'App ID URI (`api://<api-client-id>`). In caso di dubbio
incolla il token su <https://jwt.ms> e leggi `aud`.

Back-end (API + worker):
```bash
AUTH_MODE=entra
ENTRA_TENANT_ID=<tenant-id>
ENTRA_API_AUDIENCE=<api-client-id>          # oppure api://<api-client-id>
# Token di servizio worker -> API (POST /api/alerts): stringa robusta, uguale per api e worker.
INTERNAL_API_TOKEN=<stringa-lunga-casuale>
```
Front-end (SPA — variabili Vite `VITE_*`, lette a dev/build time):
```bash
VITE_AUTH_MODE=entra
VITE_ENTRA_CLIENT_ID=<spa-client-id>
VITE_ENTRA_TENANT_ID=<tenant-id>
VITE_ENTRA_API_SCOPE=api://<api-client-id>/access_as_user
```
Genera un token interno robusto:
```bash
openssl rand -hex 32
```

## 5. Come funziona nel codice
- **SPA** (`admin-console/src/auth.ts`, `main.tsx`): se `VITE_AUTH_MODE=entra`
  MSAL viene inizializzato e, senza sessione, reindirizza al login Entra
  (Authorization Code + PKCE). Il token d'accesso per lo scope dell'API viene
  acquisito in silenzio e allegato a ogni chiamata come
  `Authorization: Bearer <jwt>` (`api.ts`). Con `disabled` (default) MSAL non
  parte affatto.
- **API** (`services/api/app/auth.py`): `require_user` valida il JWT — chiavi
  pubbliche via JWKS (`.../discovery/v2.0/keys`), algoritmo RS256, `aud` =
  `ENTRA_API_AUDIENCE`, `iss` nel set atteso — ed estrae `name` e `roles`.
  Le rotte GET (fonti, alert, screening) richiedono un utente valido.
- **Endpoint interno** `POST /api/alerts`: protetto da `require_internal`
  (header `X-Internal-Token`). Lo chiama solo il worker a fine pipeline.
  Se `INTERNAL_API_TOKEN` è vuoto (dev) l'endpoint è aperto.

## 6. Verifica
1. `docker compose -f docker-compose.dev.yml up --build` con le variabili sopra.
2. Apri `http://localhost:5173`: parte il redirect a Entra, accedi, torni in console.
3. La barra in alto mostra nome utente e ruoli (dal claim `roles`).
4. Chiamata senza token → l'API risponde **401**; con token valido ma senza
   ruoli → l'utente è autenticato ma privo di privilegi RBAC (estendibile).
5. Il worker persiste l'alert con `X-Internal-Token`: se il token non combacia,
   `POST /api/alerts` risponde **401** (controlla che api e worker abbiano lo
   stesso `INTERNAL_API_TOKEN`).

## 7. Disattivare l'auth (tornare a dev)
Rimuovi/valorizza a `disabled` `AUTH_MODE` e `VITE_AUTH_MODE` (e lascia vuoto
`INTERNAL_API_TOKEN`). Nessuna dipendenza da Entra: utile per lo sviluppo locale.

## 8. Note di produzione
- Redirect URI **https** e origini CORS ristrette (`CORS_ORIGINS`).
- Ruoli via **gruppi** Entra quando gli utenti crescono (assegna il ruolo al gruppo).
- Ruota periodicamente `INTERNAL_API_TOKEN` (Key Vault / secret di Kubernetes).
- In AKS le variabili arrivano da *Secret*/*ConfigMap*; nessun segreto nell'immagine.
