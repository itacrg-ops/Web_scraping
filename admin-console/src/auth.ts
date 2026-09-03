// Autenticazione — placeholder di sviluppo.
//
// In produzione: SSO con Entra ID via MSAL (@azure/msal-browser +
// @azure/msal-react); l'API valida il JWT e applica RBAC. Qui, per far girare
// lo scaffold in locale senza Entra, l'utente è considerato autenticato.
// TODO: sostituire con MSAL e propagare il token in api.ts.

export interface DevUser {
  name: string;
  roles: string[];
}

export function useCurrentUser(): DevUser {
  return { name: "Sviluppatore (dev)", roles: ["amministratore"] };
}
