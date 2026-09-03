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

export interface Alert {
  id: string;
  subject: string;
  cf_piva?: string | null;
  cup: string[];
  ami_score: number;
  risk_level: string;
  disposition: string;
  svi_alert_id?: string | null;
  created_at: string;
}

async function getJSON<T>(path: string): Promise<T> {
  // TODO: aggiungere Authorization: Bearer <token Entra ID/MSAL>.
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export const listSources = () => getJSON<Source[]>("/api/sources");
export const listAlerts = () => getJSON<Alert[]>("/api/alerts");
export { API_BASE };
