// Client minimale verso l'API back-end (unico confine di fiducia).
// La console non parla mai direttamente con DB/LLM/SAS.

const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

export interface Source {
  id: string;
  nome: string;
  tipo: string;
  credibilita: string;
  rischio_legale: string;
  crawl_delay_s: number;
  respect_robots: boolean;
  attiva: boolean;
}

export interface EntityResolution {
  status: string;
  method: string;
  confidence: number;
  identifier_valid?: boolean;
}

export interface EvidenceItem {
  url?: string | null;
  testata?: string | null;
  title?: string | null;
  data?: string | null;
  snippet?: string | null;
  content_hash?: string | null;
  fetch_ts?: string | null;
  warc_key?: string | null;
  fonte_credibilita?: string | null;
}

export interface Alert {
  id: string;
  subject: string;
  cf_piva?: string | null;
  cup: string[];
  ami_score: number;
  risk_level: string;
  disposition: string;
  svi_alert_id?: string | null;
  entity_resolution?: EntityResolution | null;
  evidence?: EvidenceItem[];
  created_at: string;
}

async function getJSON<T>(path: string): Promise<T> {
  // TODO: aggiungere Authorization: Bearer <token Entra ID/MSAL>.
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export interface ScreeningRequest {
  denominazione: string;
  cf_piva?: string;
  cup: string[];
  seed_url?: string;
}

export interface Screening {
  id: string;
  denominazione: string;
  status: string;
  alert_id?: string | null;
  created_at: string;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export const listSources = () => getJSON<Source[]>("/api/sources");
export const listAlerts = () => getJSON<Alert[]>("/api/alerts");
export const startScreening = (body: ScreeningRequest) =>
  postJSON<Screening>("/api/screening", body);
export const getScreening = (id: string) => getJSON<Screening>(`/api/screening/${id}`);
export { API_BASE };
