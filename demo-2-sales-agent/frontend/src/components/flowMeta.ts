import type { Overview, Run } from "../lib/api";

/** The agent's working day as stations on a track. Shared by the 3D scene and the small-screen list. */
export type StationKey = "learn" | "research" | "score" | "crm" | "draft" | "followup" | "report";

export type Station = {
  key: StationKey;
  label: string;
  to: string;
  tools: string[];
  pos: [number, number];
};

export const STATIONS: Station[] = [
  { key: "learn", label: "Read the notes", to: "/profile", tools: ["read_knowledge", "save_icp"], pos: [-5.25, -0.15] },
  { key: "research", label: "Research", to: "/leads", tools: ["search_web", "read_page"], pos: [-3.5, -1.3] },
  { key: "score", label: "Score leads", to: "/leads", tools: ["save_lead", "list_leads"], pos: [-1.75, -0.15] },
  { key: "crm", label: "Check the CRM", to: "/accounts", tools: ["analyze_crm", "get_account_activity"], pos: [0, -1.3] },
  { key: "draft", label: "Write emails", to: "/approvals", tools: ["draft_outreach"], pos: [1.75, -0.15] },
  { key: "followup", label: "Follow-ups", to: "/approvals", tools: ["draft_follow_up"], pos: [3.5, -1.3] },
  { key: "report", label: "Summary", to: "/report", tools: ["finish"], pos: [5.25, -0.15] },
];

export const GATE = { label: "Your approval", to: "/approvals", pos: [2.65, 1.45] as [number, number] };

export type FlowStep = { tool: string; ok: boolean; result: string };

export function flowSteps(run: Run | null | undefined): FlowStep[] {
  if (!run) return [];
  if (run.tools_called && run.tools_called.length) return run.tools_called.map((t) => ({ tool: t.tool, ok: t.ok, result: t.result }));
  return (run.live_steps ?? []).map((s) => ({ tool: s.step, ok: s.ok !== false, result: s.result ?? "" }));
}

export const stationIndexOf = (tool: string) => STATIONS.findIndex((s) => s.tools.includes(tool));

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What each station has done so far, in words, given the steps revealed up to now. */
export function stationNotes(steps: FlowStep[], run: Run | null | undefined, accounts?: number): Record<StationKey, string> {
  const n = (tool: string, okOnly = true) => steps.filter((s) => s.tool === tool && (!okOnly || s.ok)).length;
  const refused = (key: StationKey) => {
    const tools = STATIONS.find((s) => s.key === key)?.tools ?? [];
    return steps.filter((s) => tools.includes(s.tool) && !s.ok).length;
  };
  const withRefused = (key: StationKey, text: string) => (refused(key) ? `${text}, ${refused(key)} refused` : text);
  const crmDone = n("analyze_crm") > 0;
  return {
    learn: n("read_knowledge") ? withRefused("learn", plural(n("read_knowledge"), "file read", "files read")) : "Not started",
    research: n("search_web") ? withRefused("research", plural(n("search_web"), "search", "searches")) : "Not started",
    score: n("save_lead") ? withRefused("score", plural(n("save_lead"), "lead saved", "leads saved")) : "Not started",
    crm: crmDone ? (run && run.accounts_flagged ? `${run.accounts_flagged} accounts flagged` : accounts ? `${accounts} accounts checked` : "Accounts checked") : "Not started",
    draft: n("draft_outreach", false) ? withRefused("draft", plural(n("draft_outreach"), "email", "emails")) : "Not started",
    followup: n("draft_follow_up", false) ? withRefused("followup", plural(n("draft_follow_up"), "follow-up", "follow-ups")) : "Not started",
    report: n("finish") ? "Run summary written" : "Not started",
  };
}

export function gateNote(counts: Overview["counts"] | undefined) {
  if (!counts) return "Every email waits here";
  if (counts.pending_drafts) return `${counts.pending_drafts} waiting, ${counts.sent_drafts} sent`;
  return counts.sent_drafts ? `${counts.sent_drafts} sent by you` : "Nothing waiting";
}
