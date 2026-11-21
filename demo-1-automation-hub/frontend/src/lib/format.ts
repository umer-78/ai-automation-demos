let money0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
let money2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const int = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

/** The server reports one currency for every connected account (REPORT_CURRENCY). */
export function setCurrency(code: string) {
  try {
    money0 = new Intl.NumberFormat("en-US", { style: "currency", currency: code, maximumFractionDigits: 0 });
    money2 = new Intl.NumberFormat("en-US", { style: "currency", currency: code, minimumFractionDigits: 2, maximumFractionDigits: 2 });
  } catch {
    /* unknown code: keep the previous one */
  }
}

export const money = (v: number | null | undefined, precise = false) =>
  v === null || v === undefined ? "n/a" : precise || Math.abs(v) < 100 ? money2.format(v) : money0.format(v);

/** Whole numbers stay whole; Google Ads' fractional conversions keep one decimal. */
export const count = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : int.format(v));

export const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(digits)}%`;

export const signedPct = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "n/a";
  const rounded = Math.round(v * 100);
  return rounded === 0 ? "0%" : `${rounded > 0 ? "+" : ""}${rounded}%`;
};

export function shortDate(iso: string) {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function timeAgo(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  return `${Math.round(diff / 86400)} d ago`;
}

export const workflowName: Record<string, string> = {
  client_onboarding: "Client onboarding",
  client_offboarding: "Client off-boarding",
  daily_metrics_pipeline: "Daily reporting pipeline",
  weekly_summary: "Weekly summary",
  site_draft_generate: "Website draft",
  site_draft_regenerate_section: "Regenerate section",
  airtable_bridge: "Airtable bridge",
};

export const stepName: Record<string, string> = {
  client_synced: "Client saved",
  branch_done: "Service checklist + Slack welcome",
  brief_generated: "AI brief written",
  brief_saved: "Brief saved to Airtable, draft emailed",
  done: "Onboarding complete",
  tasks_closed: "Open tasks closed",
  client_archived: "Client archived",
  airtable_updated: "Airtable updated",
  already_archived: "Already archived",
  fetched: "Rows fetched",
  upserted: "Rows upserted",
  alerts_checked: "CPA alerts checked",
};

export const channelColor: Record<string, string> = {
  "Google Ads": "var(--color-glacier)",
  "Meta Ads": "var(--color-violet)",
  SEO: "var(--color-aurora)",
};

/** Slack mrkdwn to plain text for the in-app feed (links, bold, code, emoji codes, quotes). */
export const slackText = (text: string) =>
  text
    .replace(/<[^|>]+\|([^>]+)>/g, "$1")
    .replace(/[*`]/g, "")
    .replace(/:[a-z_]+:/g, "")
    .replace(/^> /gm, "")
    .trim();
