const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function messageFrom(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => {
          const item = d as { loc?: unknown[]; msg?: string };
          const field = item.loc?.filter((p) => p !== "body").join(".");
          return field ? `${field}: ${item.msg}` : item.msg;
        })
        .join("; ");
    }
  }
  return `Request failed (HTTP ${status})`;
}

/** Access code for real client data (OWNER_TOKEN or VIEWER_TOKEN). Kept in this tab only. */
const CODE_KEY = "northwind-owner-token";
export function accessCode(): string {
  try {
    return sessionStorage.getItem(CODE_KEY) ?? "";
  } catch {
    return "";
  }
}
export function setAccessCode(code: string) {
  try {
    sessionStorage.setItem(CODE_KEY, code.trim());
  } catch {
    /* private mode: the code is asked for again */
  }
}

/** True once the server says the hub holds real data and this tab has no valid code. */
let locked = false;
const lockListeners = new Set<() => void>();
export const isLocked = () => locked;
export function onLockChange(fn: () => void) {
  lockListeners.add(fn);
  return () => void lockListeners.delete(fn);
}
function setLocked(v: boolean) {
  if (v === locked) return;
  locked = v;
  lockListeners.forEach((fn) => fn());
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const code = accessCode();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(code ? { "X-Owner-Token": code } : {}), ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (res.status === 401 && body && typeof body === "object" && "locked" in body) setLocked(true);
  if (!res.ok) throw new ApiError(res.status, messageFrom(body, res.status));
  if (path === "/api/status" && body && typeof body === "object" && "locked" in body) setLocked(Boolean((body as { locked: boolean }).locked));
  return body as T;
}

const json = (body: unknown) => (body === undefined ? undefined : JSON.stringify(body));

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: json(body) }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body: json(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  url: (path: string) => `${BASE}${path}`,
  /** Downloads through fetch so the access code travels in a header, not in the link. */
  async download(path: string, filename: string) {
    const code = accessCode();
    const res = await fetch(`${BASE}${path}`, { headers: code ? { "X-Owner-Token": code } : {} });
    if (!res.ok) throw new ApiError(res.status, `Download failed (HTTP ${res.status})`);
    const href = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href, download: filename });
    document.body.append(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(href), 1000);
  },
};

// ------------------------------------------------------------------ where the numbers come from
export type DataStatus = {
  mode: "demo" | "real";
  label: "Demo data" | "Live data" | "Your data" | "No data yet";
  live_sources: string[];
  last_sync: { at: string; status: string; source: string } | null;
  last_import: { at: string; status: string; source: string } | null;
  currency: string;
  sync_minutes: number;
};


// ------------------------------------------------------------------ types
export type Change = { spend: number | null; conversions: number | null; cpa: number | null };

export type Kpis = {
  spend: number;
  clicks: number;
  impressions: number;
  conversions: number;
  cpa: number | null;
  cpc: number | null;
  ctr: number | null;
  cvr: number | null;
};

export type Overview = {
  period: { start: string; end: string; days: number };
  previous_period: { start: string; end: string };
  totals: Kpis & { change: Change };
  clients: (Kpis & { client_id: number; client: string; status: string; change: Change; alerts: number })[];
  alerts_total: number;
};

export type CubeDay = { spend: number; conversions: number; cpa: number | null };
export type CubeRow = {
  key: string;
  client_id: number;
  client: string;
  channel: string | null;
  label: string;
  total_spend: number;
  total_conversions: number;
  median_cpa: number | null;
  days: CubeDay[];
};
export type Cube = { by: "client" | "campaign"; start: string; end: string; dates: string[]; max_spend: number; max_conversions: number; rows: CubeRow[] };

export type TrendPoint = {
  date: string;
  spend: number;
  conversions: number;
  clicks: number;
  cpa: number | null;
  by_channel: Record<string, number>;
};

export type ChannelRow = Kpis & { channel: string; share_of_spend: number };

export type Alert = {
  client_id: number;
  client: string;
  channel: string;
  cpa_this_week: number | null;
  cpa_last_week: number | null;
  change: number | null;
  spend_this_week: number;
  conversions_this_week: number;
  conversions_last_week: number;
  reason: string;
  severity: "warning" | "critical";
  week: { start: string; end: string };
};

export type Insights = {
  anomalies: { client_id: number; client: string; channel: string; date: string; cpa: number; baseline_cpa: number; z_score: number }[];
  pacing: {
    client_id: number;
    client: string;
    monthly_budget: number;
    spend_mtd: number;
    expected_mtd: number;
    projected_month: number;
    pacing: number | null;
    status: "over" | "under" | "on track";
  }[];
  forecast: { points: { date: string; spend: number }[]; slope_per_day: number; projected_total?: number };
};

export type Client = {
  id: number;
  name: string;
  website: string | null;
  industry: string | null;
  services: string[];
  manager: string | null;
  manager_email: string | null;
  status: "new" | "onboarding" | "active" | "churned" | "archived";
  brief: string | null;
  brief_data: {
    summary: string;
    audience: string;
    tone: string;
    quick_wins: string[];
    kickoff_questions?: string[];
    generated_by: string;
    website_checked?: boolean;
  } | null;
  monthly_budget: number | null;
  airtable_record_id: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  tasks_total?: number;
  tasks_open?: number;
};

export type Task = {
  id: number;
  client_id: number;
  service: string;
  title: string;
  position: number;
  status: "open" | "done" | "closed";
  due_date: string | null;
};

export type LogRow = {
  id: number;
  run_id: string;
  workflow: string;
  status: "success" | "failure";
  source: string;
  error: string | null;
  details: Record<string, unknown> & { steps?: { step: string; at_ms: number; [k: string]: unknown }[] };
  duration_ms: number | null;
  client_id: number | null;
  created_at: string;
};

export type RunStatus = {
  run_id: string;
  status: "running" | "success" | "failure";
  live: { status: string; steps: { step: string; at_ms: number; [k: string]: unknown }[]; error: string | null } | null;
  log: LogRow[];
};

export type Notification = {
  id: number;
  channel: "slack" | "email";
  kind: string;
  recipient: string | null;
  subject: string | null;
  body: string;
  status: "sent" | "simulated" | "failed";
  error: string | null;
  run_id: string | null;
  created_at: string;
};

/** Locked replies (real data, no access code) carry only app, version, data, integrations and locked. */
export type Status = {
  app: string;
  version: string;
  locked: boolean;
  data: DataStatus;
  environment?: string;
  integrations: Record<string, string>;
  counts?: { clients: number; metric_rows: number; automation_runs: number; site_drafts: number };
  latest_data_date?: string | null;
  last_pipeline_run?: LogRow | null;
  cpa_alert_threshold?: number;
};

export type AutomationStats = {
  days: number;
  success: number;
  failure: number;
  success_rate: number | null;
  workflows: { workflow: string; success: number; failure: number; avg_ms: number | null; last_run: string | null }[];
};

export type Summary = {
  client_id: number;
  client: string;
  sentences: string[];
  generated_by: string;
};

export type SiteDraft = {
  id: number;
  group_id: string;
  client_id: number | null;
  business_name: string;
  inputs: { business_name: string; industry: string; tone: string; services: string[]; colour: string };
  sections: Record<"hero" | "services" | "proof" | "cta", string>;
  html_url: string;
  storage_path: string;
  version: number;
  changed_section: string | null;
  generated_by: string;
  created_at: string;
  preview_url: string;
  palette?: { primary: string; primary_dark: string; primary_soft: string; accent: string; canvas: string };
  versions?: { version: number; changed_section: string | null; created_at: string; html_url: string }[];
};

export type PipelineResult = {
  run_id: string;
  status: string;
  source: string;
  window: { start: string; end: string };
  fetched: number;
  inserted: number;
  updated: number;
  rejected: number;
  total_rows: number;
  alerts: number;
  duration_ms: number | null;
};
