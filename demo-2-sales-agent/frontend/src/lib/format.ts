const money0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const int = new Intl.NumberFormat("en-US");

export const money = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : money0.format(v));
export const moneyK = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(2)}M` : `$${Math.round(v / 1000)}k`;
export const count = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : int.format(v));
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`);

export function shortDate(iso: string | null | undefined) {
  if (!iso) return "n/a";
  const d = new Date(iso.length <= 10 ? `${iso.length === 7 ? `${iso}-01` : iso}T00:00:00Z` : iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export function dayMonth(iso: string | null | undefined) {
  if (!iso) return "n/a";
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00Z` : iso);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}

export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "never";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  return `${Math.round(diff / 86400)} days ago`;
}

export const seconds = (ms: number | null | undefined) => (ms === null || ms === undefined ? "n/a" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

export const hostOf = (url: string | null | undefined) => {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

export const SIGNAL_LABEL: Record<string, string> = {
  compliance: "Compliance milestone",
  security_leader: "New security leader",
  security_hiring: "Security hiring",
  funding: "Funding",
  expansion: "Expansion",
  cloud: "Cloud growth",
  tech_stack: "Tech in use",
  news: "News",
};

export const CATEGORY_LABEL: Record<string, string> = {
  b2b_saas: "B2B SaaS",
  fintech: "Fintech",
  healthtech: "Healthtech",
  devtools: "Developer tools",
  data_ai: "Data and AI",
  vertical_software: "Vertical software",
  enterprise_software: "Enterprise software",
  security_vendor: "Security vendor",
  services: "Agency or IT services",
  other: "Other",
};

export const FLAG_LABEL: Record<string, string> = { stalled: "Stalled", no_contact: "No contact 30+ days", upsell: "Likely upsell" };

export const LESSON_LABEL: Record<string, string> = {
  short: "Shorter",
  soft_cta: "No meeting ask",
  question_subject: "Question subject",
  include_price: "Mentions price",
  plain_language: "Plain words",
  lead_with_fact: "Leads with the fact",
  skip_large: "Skips 1,000+",
  skip_small: "Skips under 50",
  skip_security_vendors: "Skips security vendors",
  skip_services: "Skips agencies",
  rep_length: "Rep's length",
};

export const TOOL_LABEL: Record<string, string> = {
  read_knowledge: "Read notes",
  save_icp: "Wrote ideal customer profile",
  search_web: "Searched the web",
  read_page: "Read a page",
  save_lead: "Saved and scored a lead",
  analyze_crm: "Analysed the CRM",
  get_account_activity: "Read account history",
  list_leads: "Ranked leads",
  draft_outreach: "Drafted a first email",
  draft_follow_up: "Drafted a follow-up",
  finish: "Finished",
};

export const RUN_STATUS_LABEL: Record<string, string> = {
  running: "Running",
  completed: "Completed",
  completed_with_fallback: "Completed with fallback",
  failed: "Failed",
};

export const wordCount = (text: string) => (text.match(/\b[\w'$%.-]+\b/g) ?? []).length;
