// Typed client for the sales agent API. Everything on the page comes from these calls.

export interface Status {
  engine: string; live_model: boolean; research: string; live_search: boolean; snapshot_date: string;
  database: string; slack: boolean; today: string; running_run: number | null; crm_source: "sample" | "import";
  counts: { leads: number; accounts: number; waiting: number; runs: number };
}
export interface Icp {
  summary: string; industries: string[]; size_min: number; size_max: number; regions: string[]; signals: string[];
  exclusions: string[]; edited_by?: "agent" | "rep"; updated_at?: string;
}
export interface Lead {
  id: number; company: string; website: string | null; industry: string | null; employees: number | null; employees_note: string | null;
  source_url: string; reason: string; fact: string; fact_url: string; fact_date: string | null;
  fact_precision: "day" | "month" | "year" | "none"; signals: string[];
  score: number; score_reason: string; score_parts: { fit: number; signals: number; recency: number };
  status: string; run_id: number | null; created_at: string; draft_status: string | null;
}
export interface Draft {
  id: number; lead_id: number | null; account_id: string | null; kind: "first_touch" | "follow_up"; subject: string; body: string;
  fact: string; fact_url: string; next_step: string | null; due_date: string | null;
  status: "pending" | "edited" | "approved" | "rejected" | "superseded"; original_subject: string; original_body: string;
  engine: string; run_id: number | null; created_at: string; decided_at: string | null; company: string; lead_score: number | null;
  account_owner: string | null; edited: boolean;
}
export interface Account {
  id: string; company: string; industry: string; size: number; stage: string; deal_value: number; owner: string;
  last_contact: string; stage_changed: string; notes: string; expansion_signal: string | null; flags: string[];
  days_since_contact: number; days_in_stage: number; score: number; score_reason: string; followup_waiting: boolean;
}
export interface CrmSummary { total: number; by_stage: Record<string, number>; stalled: number; untouched: number; upsell: number }
export interface Run {
  id: number; started_at: string; finished_at: string | null; status: "running" | "succeeded" | "failed"; engine: string; research: string;
  tools_called: string[]; tool_counts: Record<string, number>; input_tokens: number; output_tokens: number; feedback_used: number;
  outcome: string | null; error: string | null;
}
export interface RunEvent { id: number; run_id: number; seq: number; kind: "tool" | "note" | "error" | "done"; tool: string | null; summary: string; ms: number | null; at: string }
export interface ReportAccount { id: string; company: string; stage: string; deal_value: number; owner: string; score: number; score_reason: string; flags: string[]; days_since_contact: number; days_in_stage: number; notes: string; expansion_signal: string | null }
export interface Report {
  week: { start: string; end: string }; generated_at: string;
  counts: { new_leads: number; total_leads: number; stalled: number; untouched: number; upsell: number; waiting: number; approved: number; runs: number };
  new_leads: Pick<Lead, "id" | "company" | "website" | "score" | "score_reason" | "reason" | "fact" | "fact_url" | "status" | "created_at">[];
  top_leads: Pick<Lead, "id" | "company" | "website" | "score" | "score_reason" | "reason" | "fact" | "fact_url" | "status" | "created_at">[];
  top_accounts: ReportAccount[]; stalled: ReportAccount[]; untouched: ReportAccount[]; upsell: ReportAccount[];
  waiting: { id: number; kind: string; subject: string; status: string; due_date: string | null; company: string }[];
  decisions: { approve: number; edit: number; reject: number }; last_run: Run | null;
}
export interface ProofPair { company: string; feedback: { action: string; reason: string | null }; before: Draft; after: Draft }
export interface ImportResult { rows_read: number; accounts: number; skipped_count: number; skipped: { line: number; reason: string }[] }

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`./api${path}`, init);
  } catch {
    throw new ApiError("Can't reach the agent's server. Check your connection and try again.", 0);
  }
  if (!res.ok) {
    let detail = `The server answered ${res.status}.`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join(" ");
    } catch { /* not JSON */ }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}
const send = <T,>(method: string, path: string, body?: unknown) =>
  call<T>(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  status: () => call<Status>("/status"),
  icp: () => call<{ icp: Icp | null; default: Icp }>("/icp"),
  saveIcp: (icp: Icp) => send<{ icp: Icp }>("PUT", "/icp", icp),
  run: () => send<{ run_id: number }>("POST", "/agent/run"),
  runs: () => call<Run[]>("/agent/runs"),
  runDetail: (id: number) => call<Run & { events: RunEvent[] }>(`/agent/runs/${id}`),
  leads: () => call<Lead[]>("/leads"),
  lead: (id: number) => call<Lead & { drafts: Draft[] }>(`/leads/${id}`),
  accounts: () => call<{ summary: CrmSummary; accounts: Account[] }>("/accounts"),
  drafts: (which = "queue") => call<Draft[]>(`/drafts?which=${which}`),
  approve: (id: number) => send<Draft>("POST", `/drafts/${id}/approve`),
  edit: (id: number, subject: string, body: string) => send<Draft>("POST", `/drafts/${id}/edit`, { subject, body }),
  reject: (id: number, reason: string) => send<Draft>("POST", `/drafts/${id}/reject`, { reason }),
  proof: () => call<ProofPair[]>("/proof"),
  report: () => call<Report>("/report"),
  reset: () => send<{ accounts: number }>("POST", "/demo/reset"),
  importCrm: (csv: string) => call<ImportResult>("/crm/import", { method: "POST", headers: { "Content-Type": "text/csv" }, body: csv }),
};

export const TOOL_LABELS: Record<string, string> = {
  read_business_notes: "Notes", save_icp: "Profile", web_search: "Web search", save_lead: "Leads", read_crm: "CRM",
  score_accounts: "Scoring", create_draft: "Drafts", recommend_followup: "Follow-ups", write_report: "Report",
};
export const SIGNAL_LABELS: Record<string, string> = {
  hiring_security: "Hiring for security", compliance: "SOC 2 or ISO work", funding: "New funding",
  incident: "Recent incident", cloud_stack: "Cloud at scale",
};
export const money = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;
export const num = (n: number) => n.toLocaleString("en-US");
