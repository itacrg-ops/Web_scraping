// Client minimale verso l'API back-end (unico confine di fiducia).
// La console non parla mai direttamente con DB/LLM/SAS.

import { getToken } from "./auth";

const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

// Header comuni: aggiunge il Bearer token MSAL quando l'auth è attiva.
// In dev `getToken()` ritorna null e l'header non viene aggiunto.
async function authHeaders(extra?: Record<string, string>): Promise<Record<string, string>> {
  const headers: Record<string, string> = { ...(extra ?? {}) };
  const token = await getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

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
  warnings?: string[];
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
  tipo_soggetto?: string;
  cf_piva?: string | null;
  cup: string[];
  ami_score: number;
  risk_level: string;
  fatf_categories?: string[];
  drivers?: string[];
  disposition: string;
  svi_alert_id?: string | null;
  entity_resolution?: EntityResolution | null;
  evidence?: EvidenceItem[];
  created_at: string;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export type TipoSoggetto = "persona_giuridica" | "persona_fisica";

export interface ScreeningRequest {
  tipo_soggetto?: TipoSoggetto;
  denominazione?: string;
  nome?: string;       // solo persona fisica
  cognome?: string;    // solo persona fisica
  data_nascita?: string; // ISO YYYY-MM-DD, disambiguante (persona fisica)
  cf_piva?: string;
  cup: string[];
  seed_url?: string;       // URL singolo (override manuale)
  seed_urls?: string[];    // articoli scelti dalla web search
  max_articles?: number;   // max articoli in ricerca automatica
}

export type Credibilita = "alta" | "media" | "bassa" | "sconosciuta";

export interface SearchResult {
  url: string;
  title?: string | null;
  snippet?: string | null;
  testata?: string | null;
  domain?: string | null;
  testata_credibilita?: Credibilita | null;
  data?: string | null;
  language?: string | null;
  provider: string;
  score?: number | null;
}

export interface SearchResponse {
  provider: string;
  query: string;
  mode: string;
  count: number;
  raw_count: number;
  removed: number;
  min_credibility: string;
  note?: string | null;
  results: SearchResult[];
}

export interface SearchPreviewRequest {
  tipo_soggetto: TipoSoggetto;
  denominazione?: string;
  nome?: string;
  cognome?: string;
  cf_piva?: string;
  mode?: "broad" | "targeted";
  max_results?: number;
  min_credibility?: "none" | "bassa" | "sconosciuta" | "media" | "alta";
}

export interface Screening {
  id: string;
  denominazione: string;
  tipo_soggetto?: TipoSoggetto;
  status: string;
  alert_id?: string | null;
  created_at: string;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
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
export const searchPreview = (body: SearchPreviewRequest) =>
  postJSON<SearchResponse>("/api/search/preview", body);
export { API_BASE };
