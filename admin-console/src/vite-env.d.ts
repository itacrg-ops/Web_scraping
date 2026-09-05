/// <reference types="vite/client" />

// Tipizzazione delle variabili d'ambiente Vite usate dalla console.
// Tutte opzionali: in dev restano assenti (auth disabilitata, API su localhost).
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_AUTH_MODE?: string;
  readonly VITE_ENTRA_CLIENT_ID?: string;
  readonly VITE_ENTRA_TENANT_ID?: string;
  readonly VITE_ENTRA_API_SCOPE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
