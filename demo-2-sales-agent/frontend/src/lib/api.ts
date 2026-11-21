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
    if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
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

/**
 * Static preview (the hosted link): instead of a server, the app reads a snapshot of real answers
 * from the API, saved by scripts/build_preview.py. Nothing can be changed in this mode.
 */
export const PREVIEW = import.meta.env.VITE_STATIC_PREVIEW === "1";
export const PREVIEW_NOTE = "This is a read-only preview. Run the app from the repo to try this.";
let snapshot: Promise<Record<string, unknown>> | null = null;

export function snapshotKey(path: string) {
  const [p, q] = path.split("?");
  if (!q) return p;
  const params = new URLSearchParams(q);
  params.sort();
  return `${p}?${params.toString()}`;
}

async function fromSnapshot<T>(path: string): Promise<T> {
  snapshot ??= fetch("./demo-snapshot.json").then((r) => r.json() as Promise<Record<string, unknown>>);
  const data = await snapshot;
  const key = snapshotKey(path);
  if (key in data) return structuredClone(data[key]) as T;
  throw new ApiError(404, "This view is not part of the preview.");
}

/** Access code for your own CRM data (OWNER_TOKEN or VIEWER_TOKEN). Kept in this tab only. */
const CODE_KEY = "acme-owner-token";
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

/** True once the server says the app holds real CRM data and this tab has no valid code. */
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
  if (PREVIEW) {
    if (init?.method && init.method !== "GET") throw new ApiError(0, PREVIEW_NOTE);
    return fromSnapshot<T>(path);
  }
  const code = accessCode();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(code ? { "X-Owner-Token": code } : {}), ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (res.status === 401 && body && typeof body === "object" && "locked" in body) setLocked(true);
  if (!res.ok) throw new ApiError(res.status, messageFrom(body, res.status));
  return body as T;
}

const json = (body: unknown) => (body === undefined ? undefined : JSON.stringify(body));

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: json(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: json(body) }),
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

/** Where the CRM comes from and what a real-data run still needs. */
export type DataStatus = {
  mode: "demo" | "real";
  label: "Sample CRM" | "Your CRM" | "Live from HubSpot" | "No CRM data yet";
  crm_source: "sample" | "csv" | "hubspot" | null;
  accounts: number;
  last_sync: { at: string; status: string; kind: string } | null;
  needs: ("product" | "anthropic" | "tavily")[];
  research: string;
  ai: string;
  sync_minutes: number;
};

// ------------------------------------------------------------------ types
export type ScoreParts = { fit: number; signals: number; recency: number };

export type Fact = { fact: string; url: string; date: string | null; type: string; title?: string; source?: string };

export type Lead = {
  id: number;
  company: string;
  domain: string | null;
  industry: string | null;
  category: string;
  size_band: string;
  region: string;
  cloud_native: string;
  source_url: string;
  reason: string;
  facts: Fact[];
  score: number;
  score_reason: string;
  score_parts: ScoreParts | null;
  status: "new" | "drafted" | "approved" | "contacted" | "excluded";
  excluded_reason: string | null;
  research_source: string | null;
  created_at: string;
  updated_at: string;
  drafts?: Draft[];
};

export type Activity = { id: number; account_id: number; kind: string; direction: string; summary: string; occurred_at: string };

export type Account = {
  id: number;
  company: string;
  domain: string;
  industry: string;
  category: string;
  size: number | null;
  region: string;
  cloud_provider: string;
  stage: "Prospect" | "Discovery" | "Proposal" | "Customer";
  deal_value: number | null;
  arr: number | null;
  plan: string | null;
  cloud_accounts_used: number | null;
  cloud_accounts_limit: number | null;
  renewal_date: string | null;
  stage_entered_at: string;
  last_contact: string | null;
  owner: string;
  contact_name: string;
  contact_title: string;
  contact_email: string;
  notes: string;
  score: number | null;
  score_reason: string | null;
  score_parts: ScoreParts | null;
  flags: string[] | null;
  flag_reasons: Record<string, string> | null;
  analyzed_at: string | null;
  activity?: Activity[];
  drafts?: Draft[];
};

export type Feedback = {
  id: number;
  draft_id: number;
  action: "approve" | "edit" | "reject" | "mark_sent";
  reason: string | null;
  edited_subject: string | null;
  edited_body: string | null;
  reviewer: string | null;
  created_at: string;
};

export type DraftStatus = "pending" | "approved" | "edited" | "rejected" | "sent";

export type Draft = {
  id: number;
  kind: "outreach" | "follow_up";
  lead_id: number | null;
  account_id: number | null;
  run_id: string | null;
  recipient: string | null;
  recipient_name: string | null;
  subject: string;
  body: string;
  original_subject: string;
  original_body: string;
  cited_fact: string | null;
  source_url: string | null;
  next_step: string | null;
  send_date: string | null;
  status: DraftStatus;
  lessons_applied: string[] | null;
  previous_draft_id: number | null;
  generated_by: "ai" | "template";
  word_count: number | null;
  reviewer: string | null;
  reviewed_at: string | null;
  sent_at: string | null;
  created_at: string;
  company?: string;
  lead_score?: number | null;
  lead_score_parts?: ScoreParts | null;
  lead_score_reason?: string | null;
  account_score?: number | null;
  account_flags?: string[] | null;
  account_stage?: string | null;
  account_owner?: string | null;
  feedback?: Feedback[];
  has_recorded_approval?: boolean;
  previous_draft?: Draft | null;
};

export type ToolCall = { tool: string; via: string; ok: boolean; ms: number; at_ms: number; input: Record<string, unknown>; result: string };
export type LiveStep = { step: string; at_ms: number; ok?: boolean; via?: string; result?: string };

export type Run = {
  id: string;
  trigger: string;
  mode: "live" | "offline";
  model: string | null;
  research_source: string | null;
  status: "running" | "completed" | "completed_with_fallback" | "failed";
  outcome: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  tools_called?: ToolCall[];
  tool_call_count: number;
  tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  turns: number;
  leads_scored: number;
  leads_created: number;
  drafts_created: number;
  followups_created: number;
  accounts_flagged: number;
  feedback_ids: number[];
  context_feedback?: string | null;
  lessons?: Lessons | null;
  icp_version: number | null;
  summary: string | null;
  error: string | null;
  live_steps?: LiveStep[];
};

export type LeadCard = {
  id: number;
  company: string;
  score: number;
  parts: ScoreParts;
  status: Lead["status"];
  category: string;
  region: string;
  reason: string;
  signal: string | null;
  fact: string | null;
  source_url: string;
  fact_date: string | null;
};

export type AccountCard = { id: number; company: string; stage: string; owner: string; score: number | null; flags: string[]; why: string; value: number | null };

export type Overview = {
  integrations: Record<string, string>;
  running: string | null;
  latest_run: Run | null;
  icp: { version: number; author: string; summary: string };
  counts: {
    leads: number;
    active_leads: number;
    avg_lead_score: number | null;
    hot_leads: number;
    accounts: number;
    crm_analysed: boolean;
    stalled: number;
    no_contact: number;
    upsell: number;
    pending_drafts: number;
    approved_drafts: number;
    rejected_drafts: number;
    sent_drafts: number;
    open_pipeline: number;
  };
  top_leads: LeadCard[];
  top_accounts: AccountCard[];
  radar: LeadCard[];
};

export type Rule = { key: string; text: string; feedback_ids: number[] };
export type Lessons = {
  max_words: number;
  soft_cta: boolean;
  question_subject: boolean;
  include_price: boolean;
  plain_language: boolean;
  lead_with_fact: boolean;
  skip_size_bands: string[];
  skip_categories: string[];
  rules: Rule[];
};

export type DraftStats = {
  id: number;
  run_id: string | null;
  status: DraftStatus;
  subject: string;
  body: string;
  words: number;
  meeting_ask: boolean;
  lessons_applied: string[];
  created_at: string;
};

export type FeedbackItem = Feedback & { draft_kind: string; draft_subject: string; original_subject: string; original_body: string; company: string };

export type Learning = {
  context_block: string;
  feedback: FeedbackItem[];
  lessons: Lessons;
  pairs: { company: string | null; before: DraftStats; after: DraftStats; feedback: Feedback | null }[];
  runs: {
    run_id: string;
    started_at: string;
    mode: string;
    feedback_in_context: number;
    rules_in_context: number;
    drafts: number;
    avg_words: number;
    meeting_asks: number;
    reviewed: number;
    approval_rate: number | null;
  }[];
};

export type AgentContext = {
  feedback_ids: number[];
  feedback_block: string;
  lessons: Lessons;
  icp_version: number;
  system_prompt: string;
  mode: string;
};

export type IcpCriteria = {
  summary: string;
  target_categories: string[];
  adjacent_categories: string[];
  excluded_categories: string[];
  employee_min: number;
  employee_max: number;
  regions: string[];
  signal_weights: Record<string, number>;
  exclusions: string[];
};

export type IcpVersion = {
  id?: number;
  version: number;
  author: "agent" | "rep" | "default";
  summary: string;
  criteria: IcpCriteria;
  note?: string | null;
  run_id?: string | null;
  created_at: string | null;
};

export type IcpPayload = {
  active: IcpVersion;
  history: IcpVersion[];
  rep_edited: boolean;
  options: { categories: Record<string, string>; regions: string[]; signals: Record<string, string>; size_bands: string[] };
};

export type IcpChange = {
  lead_id: number;
  company: string;
  old_score: number;
  new_score: number;
  delta: number;
  old_status: string;
  new_status: string;
  score_reason: string;
};

export type ReportAccount = { id: number; company: string; owner: string; stage: string; score: number; flags: string[]; why: Record<string, string>; reason: string; value: number | null };

export type Report = {
  generated_at: string;
  period: { start: string; end: string; label: string };
  headline: string[];
  leads: { new_this_week: number; total: number; top: { id: number; company: string; score: number; reason: string; score_reason: string; status: string; source_url: string }[] };
  pipeline: { open_value: number; stalled_value: number; top_accounts: ReportAccount[] };
  stalled: ReportAccount[];
  no_contact: ReportAccount[];
  upsell: ReportAccount[];
  pending_drafts: { id: number; kind: string; subject: string; send_date: string | null; created_at: string; company: string }[];
  reviews: { approved: number; edited: number; rejected: number; sent: number; approval_rate: number | null; recent_rejection_reasons: string[] };
  agent: { runs: number; avg_duration_s: number | null; tokens: number; cost_usd: number; tool_calls: number };
  icp_version: number;
};

export type Notification = { id: number; channel: string; kind: string; recipient: string | null; body: string; status: string; error: string | null; run_id: string | null; created_at: string };

export type LogRow = {
  id: number;
  run_id: string;
  workflow: string;
  status: "success" | "failure";
  source: string;
  error: string | null;
  details: Record<string, unknown>;
  duration_ms: number | null;
  created_at: string;
  step_count: number;
};

export type KnowledgeDoc = { name: string; title: string; files: string[]; characters: number; content: string };
