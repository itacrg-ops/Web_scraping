// Autenticazione della console — SSO con Entra ID (MSAL).
//
// Due modalità, scelte via `VITE_AUTH_MODE`:
//   - assente / "disabled" (default): nessun login, utente dev fittizio.
//     Tiene in piedi lo sviluppo locale su Docker Desktop senza Entra.
//   - "entra": flusso MSAL (redirect). Il token d'accesso viene propagato
//     all'API in `api.ts` come `Authorization: Bearer <jwt>`; l'API valida
//     firma/audience/issuer e applica l'RBAC.
//
// Config (solo in modalità "entra"), via variabili Vite `VITE_*`:
//   VITE_ENTRA_CLIENT_ID   client id dell'app SPA registrata su Entra
//   VITE_ENTRA_TENANT_ID   tenant id (GUID) — default "organizations"
//   VITE_ENTRA_API_SCOPE   scope dell'API protetta (es. api://<api-id>/access_as_user)
// Guida: docs/MSAL_ENTRA_SETUP.md

import {
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
  type Configuration,
  type RedirectRequest,
} from "@azure/msal-browser";

export const AUTH_ENABLED: boolean =
  (import.meta.env.VITE_AUTH_MODE as string | undefined) === "entra";

const CLIENT_ID = (import.meta.env.VITE_ENTRA_CLIENT_ID as string | undefined) ?? "";
const TENANT_ID = (import.meta.env.VITE_ENTRA_TENANT_ID as string | undefined) ?? "organizations";
const API_SCOPE = (import.meta.env.VITE_ENTRA_API_SCOPE as string | undefined) ?? "";

const msalConfig: Configuration = {
  auth: {
    clientId: CLIENT_ID,
    authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    redirectUri: window.location.origin,
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    // sessionStorage: il token non sopravvive alla chiusura della scheda.
    cacheLocation: "sessionStorage",
  },
};

// Istanza creata SOLO quando l'auth è attiva: in dev resta null e MSAL non
// viene mai inizializzato (nessuna dipendenza da Entra per girare in locale).
export const msalInstance: PublicClientApplication | null = AUTH_ENABLED
  ? new PublicClientApplication(msalConfig)
  : null;

// Scope richiesti al login. Se l'API scope non è configurato, si chiede solo
// l'identità (openid/profile): l'app parte comunque, ma senza token per l'API.
export const loginRequest: RedirectRequest = {
  scopes: API_SCOPE ? [API_SCOPE] : ["openid", "profile"],
};

export interface CurrentUser {
  name: string;
  roles: string[];
}

const DEV_USER: CurrentUser = {
  name: "Sviluppatore (dev)",
  roles: ["amministratore", "auditor"],
};

function accountToUser(account: AccountInfo | null): CurrentUser {
  if (!account) return DEV_USER;
  const claims = (account.idTokenClaims ?? {}) as Record<string, unknown>;
  const roles = Array.isArray(claims.roles) ? (claims.roles as string[]) : [];
  return { name: account.name ?? account.username ?? "utente", roles };
}

function activeAccount(): AccountInfo | null {
  if (!msalInstance) return null;
  return msalInstance.getActiveAccount() ?? msalInstance.getAllAccounts()[0] ?? null;
}

// Non è un hook React (nessuno useState): lettura sincrona dell'account attivo.
// L'account non cambia durante la sessione, quindi va bene per la barra utente.
export function useCurrentUser(): CurrentUser {
  if (!AUTH_ENABLED) return DEV_USER;
  return accountToUser(activeAccount());
}

// Token d'accesso per l'API. `null` in dev (l'API in "disabled" non lo richiede).
export async function getToken(): Promise<string | null> {
  if (!AUTH_ENABLED || !msalInstance || !API_SCOPE) return null;
  const account = activeAccount();
  if (!account) return null;
  try {
    const res = await msalInstance.acquireTokenSilent({ scopes: [API_SCOPE], account });
    return res.accessToken;
  } catch (err) {
    // Sessione scaduta / consenso necessario: rimanda al login interattivo.
    if (err instanceof InteractionRequiredAuthError) {
      await msalInstance.acquireTokenRedirect({ scopes: [API_SCOPE], account });
    }
    return null;
  }
}

export async function logout(): Promise<void> {
  if (msalInstance) await msalInstance.logoutRedirect();
}
