// Typed client for the hub API (same origin; /api is proxied in development).

export type Service = "SEO" | "Paid Ads" | "Web Design";
export const SERVICES: Service[] = ["SEO", "Paid Ads", "Web Design"];
export const CHANNELS = ["Google Ads", "Meta Ads", "SEO"] as const;

export interface Status {
  ok: boolean; today: string; engine: string; live_model: boolean; database: string;
  latest_data: string | null; clients: number;
  integrations: { airtable: boolean; make_webhooks: boolean; slack: boolean; supabase_storage: boolean; email: boolean };
}
export interface Kpis { spend: number; clicks: number; conversions: number; cpa: number | null; cpc: number | null; window: string[] }
export interface ClientRow { client_id: string; client: string; status: string; spend: number; clicks: number; conversions: number; cpa: number | null; wow: Record<string, number | null>; alerts: string[]; simulated: boolean }
export interface Alert { client_id: string; client: string; channel: string; cpa_now: number; cpa_prev: number; change_pct: number }
export interface Dashboard {
  today: string; kpis: Kpis; trend: { date: string; spend: number; conversions: number }[];
  channels: { channel: string; spend: number; clicks: number; conversions: number; cpa: number | null }[];
  by_client: ClientRow[]; matrix: { client_id: string; channel: string; spend: number; conversions: number; cpa: number | null }[];
  alerts: Alert[]; threshold_pct: number; windows: Record<string, string[]>;
  sample_basis: SampleBasis;
}
export interface SampleBasis {
  sources: Record<"Google Ads" | "Meta Ads", { title: string; url: string }>;
  clients: { client_id: string; client: string; category: string; google: { cpc: number; cpl: number };
    meta: { cpc: number; cpl: number; note: string | null }; daily_budget: Record<string, number> }[];
}
export interface Client {
  id: string; name: string; website: string | null; industry: string | null; services: Service[];
  manager: string | null; manager_email: string | null; status: string; airtable_record_id: string | null;
  brief: { audience: string; tone: string; quick_wins: string[]; service: string; engine: string } | null;
  open_tasks?: number; closed_tasks?: number;
}
export interface Step { name: string; status: "ok" | "skipped" | "saved" | "failed"; detail: string }
export interface OnboardingResult {
  client: string; client_id: string; service: Service; steps: Step[]; checklist: string[];
  slack: { text: string; sent: boolean; detail: string };
  brief: { audience: string; tone: string; quick_wins: string[] }; engine: string;
  email: { to: string | null; subject: string; body: string; sent: boolean; detail: string }; elapsed_s: number;
}
export interface LogRow { id: number; workflow: string; status: string; error: string | null; detail: string | null; created_at: string }
export interface SiteDraft {
  id: number; site_id: string; business_name: string; industry: string; tone: string; services: string[];
  colour: string; html: string; html_url: string; version: number; section: string; engine: string;
  preview_url: string; storage?: { sent: boolean; detail: string; url: string | null };
  versions?: { version: number; section: string; engine: string; url: string; created_at: string }[];
}
export interface WeeklySummary { engine: string; week: string; clients: { client_id: string; client: string; sentences: string[]; change_pct: number | null; alerts: { channel: string; change_pct: number }[] }[] }
export interface Integrity { all_ok: boolean; today: string; checks: { name: string; ok: boolean; detail: string }[] }
export interface Lineage { today: string; metrics: { metric: string; sql: string; params: Record<string, string>; rows: number; sample: Record<string, unknown>[] }[] }

export class ApiError extends Error {}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`./api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail)) msg = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch { /* keep the status text */ }
    throw new ApiError(msg);
  }
  return (await res.json()) as T;
}

const post = <T,>(path: string, body: unknown = {}) => call<T>(path, { method: "POST", body: JSON.stringify(body) });

export interface ImportResult {
  rows_read: number; rows_used: number; days_written: number; skipped_count: number; skipped: { line: number; reason: string }[];
  unknown_clients: string[]; date_range: [string, string] | null; clients: string[]; upserted: number; duplicate_rows: number;
}

export const api = {
  status: () => call<Status>("/status"),
  dashboard: () => call<Dashboard>("/dashboard"),
  clients: () => call<Client[]>("/clients"),
  log: (limit = 30) => call<LogRow[]>(`/log?limit=${limit}`),
  addClient: (c: { name: string; website?: string; industry?: string; services: Service[]; manager?: string; manager_email?: string }) =>
    post<{ client: Client; airtable: { sent: boolean; detail: string }; onboarding: OnboardingResult[]; mode: string }>("/clients", c),
  onboard: (client_id: string, service: Service) => post<OnboardingResult>("/onboarding", { client_id, service }),
  churn: (id: string) => post<{ client: string; tasks_closed: number; slack: { text: string; sent: boolean; detail: string } }>(`/clients/${id}/churn`),
  forcedFailure: () => post<{ logged: boolean; error: string; slack: { sent: boolean; detail: string } }>("/test/forced-failure"),
  importAds: (csv: string, channel: string) =>
    call<ImportResult>(`/reporting/import${channel ? `?channel=${encodeURIComponent(channel)}` : ""}`,
      { method: "POST", headers: { "Content-Type": "text/csv" }, body: csv }),
  runJob: () => post<{ upserted: number; duplicate_rows: number; span: string; source: string }>("/reporting/job", { source: "mock-api" }),
  weekly: (refresh = false) => post<WeeklySummary>("/reporting/weekly-summary", { refresh }),
  newSite: (s: { business_name: string; industry: string; tone: string; services: string[]; colour: string }) => post<SiteDraft>("/sites", s),
  site: (id: string) => call<SiteDraft>(`/sites/${id}`),
  regenerate: (id: string, section: string, instructions: string) => post<SiteDraft>(`/sites/${id}/regenerate`, { section, instructions }),
  integrity: () => call<Integrity>("/integrity"),
  lineage: () => call<Lineage>("/lineage"),
  reset: () => post<{ clients: number; metric_rows: number }>("/demo/reset"),
};

export const money = (n: number | null | undefined, digits = 0) =>
  n == null ? "—" : `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
export const num = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("en-US"));
export const pct = (n: number | null | undefined) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`);
