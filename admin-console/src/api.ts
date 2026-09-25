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

// Motori di ricerca web (search-gateway): stato live per la pagina Fonti.
export interface SearchProvider {
  id: string;
  nome: string;
  tipo: string;
  keyless: boolean;
  configurato: boolean;
  attivo: boolean;
  note?: string | null;
}

export interface SearchProvidersStatus {
  active: string[];
  count: number;
  fan_out: boolean;
  providers: SearchProvider[];
}

export interface EntityResolution {
  status: string;
  method: string;
  confidence: number;
  identifier_valid?: boolean;
  warnings?: string[];
}

export interface EvidenceItem {
  id?: string | null;
  url?: string | null;
  testata?: string | null;
  title?: string | null;
  data?: string | null;
  snippet?: string | null;
  content_hash?: string | null;
  fetch_ts?: string | null;
  warc_key?: string | null;
  fonte_credibilita?: string | null;
  // Predizione del sistema: il soggetto è citato nell'articolo? (e come)
  mentioned?: boolean | null;
  mention_match?: string[] | null;
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
  // Esito della pubblicazione in SVI (l'alert è salvato prima di pubblicare).
  svi_status?: "pending" | "published" | "failed" | "skipped";
  svi_error?: string | null;
  entity_resolution?: EntityResolution | null;
  classification?: { method?: string | null; [k: string]: unknown } | null;
  // Nomi simili citati negli articoli al posto del nome esatto (possibile refuso).
  name_variants?: string[];
  // Persona fisica: ruoli scritti accanto al nome negli articoli e possibile PEP.
  roles?: RoleFound[];
  pep?: boolean | null;
  // Stesso soggetto scritto in modi diversi (duplicati): calcolata dall'API.
  subject_key: string;
  evidence?: EvidenceItem[];
  created_at: string;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: await authHeaders() });
  if (!res.ok) throw await errorOf(res);
  return (await res.json()) as T;
}

export type TipoSoggetto = "persona_giuridica" | "persona_fisica";

// Ruolo della persona trovato negli articoli (worker, roles.py).
export interface RoleFound {
  ruolo: string;                              // come scritto: "sindaco di Roma", "AD di Acme"
  tipo: string;                               // tipo: "sindaco", "amministratore delegato"…
  categoria: "pep" | "politico" | "aziendale" | "pubblico";
  pep: "si" | "verifica" | null;              // carica dell'elenco PEP (D.Lgs. 231/2007)
  ex: boolean;                                // carica cessata
  articoli?: number;
}

export interface ScreeningRequest {
  tipo_soggetto?: TipoSoggetto;
  denominazione?: string;
  nome?: string;       // solo persona fisica
  cognome?: string;    // solo persona fisica
  data_nascita?: string; // ISO YYYY-MM-DD, disambiguante (persona fisica)
  luogo_nascita?: string; // comune/stato di nascita, disambiguante (persona fisica)
  cf_piva?: string;
  azienda?: string;    // persona fisica: qualificatore ricerca (AND)
  localita?: string;   // persona fisica: qualificatore ricerca (AND)
  ruolo?: string;      // persona fisica: soft (corroborazione, non in query)
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
  azienda?: string;
  localita?: string;
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

// Registro soggetti noti (anti-omonimia) — gestibile dalla console.
export interface Subject {
  id: string;
  tipo_soggetto: TipoSoggetto;
  denominazione: string;
  cf_piva?: string | null;
  data_nascita?: string | null;
  luogo_nascita?: string | null;
  cup: string[];
  ruolo?: string | null;
  attivo: boolean;
  created_at: string;
  pep?: boolean;                  // persona politicamente esposta (confermata)
  cariche?: string[];             // ruoli dagli articoli, confermati
  alias?: string[];               // varianti confermate dello stesso soggetto
  distinti?: string[];            // nomi simili confermati come ALTRI soggetti
  articoli_confermati?: number;   // notizie verificate dai revisori
}

export interface SubjectCreate {
  tipo_soggetto: TipoSoggetto;
  denominazione?: string;
  nome?: string;
  cognome?: string;
  data_nascita?: string;
  luogo_nascita?: string;
  cf_piva?: string;
  cup: string[];
  ruolo?: string;
  pep?: boolean;
  cariche?: string[];
}

// Modifica parziale: solo i campi inviati vengono applicati.
export interface SubjectUpdate {
  denominazione?: string;
  cf_piva?: string;
  data_nascita?: string;
  luogo_nascita?: string;
  cup?: string[];
  ruolo?: string;
  attivo?: boolean;
  pep?: boolean;
  cariche?: string[];
}

export interface SubjectImportResult {
  created: number;
  updated: number;
  errors: string[];
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await errorOf(res);
  return (await res.json()) as T;
}

async function patchJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await errorOf(res);
  return (await res.json()) as T;
}

async function deleteReq(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE", headers: await authHeaders() });
  if (!res.ok) throw await errorOf(res);
}

// Errore leggibile: usa il `detail` dell'API (es. cosa manca per un caso "affidabile").
async function errorOf(res: Response): Promise<Error> {
  let detail = "";
  try {
    const body = await res.json();
    detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch {
    /* corpo non JSON */
  }
  return new Error(detail ? `${res.status}: ${detail}` : `${res.status} ${res.statusText}`);
}

async function putJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await errorOf(res);
  return (await res.json()) as T;
}

// --- Etichette dei casi (dataset di valutazione) ---
// Stessa lista del llm-gateway: etichette confrontabili con le predizioni.
export const FATF_CATEGORIES = [
  "Fraud & Financial Crime", "Corruption & Bribery", "Money Laundering", "Organized Crime",
  "Terrorist Financing", "Tax Crimes", "Sanctions & Embargoes", "Trafficking (Human/Drugs/Arms)",
  "Environmental Crime", "Cybercrime", "Market Manipulation & Securities", "Regulatory & Compliance",
];

export type Pertinenza = "si" | "omonimo" | "non_citato" | "incerto";
export type Avversa = "si" | "no" | "incerto";
export type Ruolo = "autore_indagato" | "vittima" | "menzionato" | "non_determinabile";
export type DispositionAttesa = "ESCALATION_I_LIVELLO" | "AUTO_CHIUSO";

export interface EvidenceLabel {
  pertinenza?: Pertinenza | null;
  avversa?: Avversa | null;
}

export interface CaseLabelIn {
  evidence_labels: Record<string, EvidenceLabel>;
  categorie_corrette: string[];
  ruolo?: Ruolo | null;
  disposition_attesa?: DispositionAttesa | null;
  affidabile: boolean;
  note?: string | null;
}

export interface CaseLabel extends CaseLabelIn {
  id: string;
  alert_id: string;
  reviewer: string;
  reviewer_name?: string | null;
  updated_at?: string | null;
}

export interface CaseLabelSummary {
  alert_id: string;
  affidabile: boolean;
  updated_at?: string | null;
}

export interface LabelStats {
  etichettati: number;
  affidabili: number;
  revisori: number;
  per_disposition: Record<string, number>;
  affidabili_per_disposition: Record<string, number>;
}

export const getLabel = (alertId: string) => getJSON<CaseLabel | null>(`/api/alerts/${alertId}/label`);
export const saveLabel = (alertId: string, body: CaseLabelIn) =>
  putJSON<CaseLabel>(`/api/alerts/${alertId}/label`, body);
export const listMyLabels = () => getJSON<CaseLabelSummary[]>("/api/labels");
export const getLabelStats = () => getJSON<LabelStats>("/api/labels/stats");

// Scarica il dataset (NDJSON). fetch + blob: serve l'header Authorization (MSAL).
export async function downloadDataset(soloAffidabili = true): Promise<void> {
  const res = await fetch(`${API_BASE}/api/labels/export?solo_affidabili=${soloAffidabili}`,
    { headers: await authHeaders() });
  if (!res.ok) throw await errorOf(res);
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1]
    ?? "dataset-casi.ndjson";
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export const listSources = () => getJSON<Source[]>("/api/sources");
export const getSearchProviders = () => getJSON<SearchProvidersStatus>("/api/search/providers");
export const listAlerts = () => getJSON<Alert[]>("/api/alerts");
export const getAlert = (id: string) => getJSON<Alert>(`/api/alerts/${id}`);
export const startScreening = (body: ScreeningRequest) =>
  postJSON<Screening>("/api/screening", body);
export const getScreening = (id: string) => getJSON<Screening>(`/api/screening/${id}`);
export const searchPreview = (body: SearchPreviewRequest) =>
  postJSON<SearchResponse>("/api/search/preview", body);
export const listSubjects = () => getJSON<Subject[]>("/api/subjects");
export const createSubject = (body: SubjectCreate) => postJSON<Subject>("/api/subjects", body);
export const updateSubject = (id: string, body: SubjectUpdate) =>
  patchJSON<Subject>(`/api/subjects/${id}`, body);
export const deleteSubject = (id: string) => deleteReq(`/api/subjects/${id}`);
export const importSubjects = (csvText: string) =>
  postJSON<SubjectImportResult>("/api/subjects/import", { csv: csvText });
export { API_BASE };

// --- Cancellazione di alert duplicati o errati -------------------------------------
export type MotivoCancellazione = "duplicato" | "errato";

export interface AlertDeleteResult {
  eliminati: number;
  etichette_eliminate: number;
  in_svi: { id: string; svi_alert_id: string }[];   // restano aperti in SAS VI
}

export const deleteAlerts = (ids: string[], motivo: MotivoCancellazione, nota?: string) =>
  postJSON<AlertDeleteResult>("/api/alerts/delete", { ids, motivo, nota: nota || null });

// --- Casi collegati (etichettatura) -------------------------------------------------
export interface RelatedCase {
  id: string;
  subject: string;
  created_at: string;
  disposition: string;
  etichette: number;
  affidabili: number;
  mia: "affidabile" | "bozza" | null;
}

export interface PriorJudgment {
  alert_id: string;
  created_at: string;
  pertinenza?: Pertinenza | null;
  avversa?: Avversa | null;
}

export interface RegistryArticle {
  pertinenza: Pertinenza;
  avversa: Avversa;
  confirmed_by_name?: string | null;
  confirmed_at?: string | null;
}

export interface RelatedOut {
  stesso_soggetto: RelatedCase[];
  giudizi_precedenti: Record<string, PriorJudgment[]>;   // evidence_id → miei giudizi altrove
  registro: {
    subject_id: string;
    denominazione: string;
    come: "entity_resolution" | "cf_piva" | "nome" | "alias";
    articoli: Record<string, RegistryArticle>;           // evidence_id → già confermato
  } | null;
}

export const getRelated = (alertId: string) => getJSON<RelatedOut>(`/api/alerts/${alertId}/related`);

// --- Nomi simili (prima di uno screening o di aggiungere un soggetto) --------------
export interface SimilarCandidate {
  fonte: "registro" | "screening";
  subject_id?: string | null;
  denominazione: string;
  tipo_soggetto: TipoSoggetto;
  cf_piva?: string | null;
  data_nascita?: string | null;
  luogo_nascita?: string | null;
  score: number;
  alert: number;
}

export interface SimilarOut {
  nome: string;
  registro_esatto: SimilarCandidate | null;
  alert_esistenti: number;
  simili: SimilarCandidate[];
}

// Con cf_piva e data_nascita, «registro_esatto» è il soggetto già inserito secondo la
// regola dell'API (stesso CF/P.IVA; stesso nome senza CF/P.IVA o data di nascita diversi).
export function similarSubjects(q: { tipo_soggetto: TipoSoggetto; denominazione?: string;
                                     nome?: string; cognome?: string; cf_piva?: string;
                                     data_nascita?: string }) {
  const params = new URLSearchParams();
  Object.entries(q).forEach(([k, v]) => { if (v) params.set(k, v); });
  return getJSON<SimilarOut>(`/api/subjects/similar?${params}`);
}

export const decideName = (subjectId: string, name: string, decision: "stesso" | "diverso") =>
  postJSON<Subject>(`/api/subjects/${subjectId}/names`, { name, decision });

// --- Conferma degli articoli nel registro (a valle dell'etichettatura) -------------
export interface SubjectArticle {
  id: string;
  alert_id?: string | null;
  url: string;
  testata?: string | null;
  title?: string | null;
  data?: string | null;
  pertinenza: Pertinenza;
  avversa: Avversa;
  categorie: string[];
  ruolo?: Ruolo | null;
  esito?: DispositionAttesa | null;
  confirmed_by_name?: string | null;
  confirmed_at?: string | null;
}

export interface ConfirmOut {
  subject: Subject;
  nuovo_soggetto: boolean;              // creato ora (altrimenti era già nel registro)
  confermati: number;
  saltati: number;
  alias_aggiunto?: string | null;
}

export const confirmInRegistry = (alertId: string,
                                  target: ({ subject_id: string } | { nuovo: SubjectCreate })
                                    & { cariche?: string[]; pep?: boolean }) =>
  postJSON<ConfirmOut>(`/api/alerts/${alertId}/confirm`, target);
export const listSubjectArticles = (subjectId: string) =>
  getJSON<SubjectArticle[]>(`/api/subjects/${subjectId}/articles`);
export const removeSubjectArticle = (subjectId: string, articleId: string) =>
  deleteReq(`/api/subjects/${subjectId}/articles/${articleId}`);

