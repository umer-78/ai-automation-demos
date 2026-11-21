/** Steps of the onboarding automation, shared by the 3D scene and its caption. */
export type FlowNodeKey = "intake" | "make" | "seo" | "ads" | "web" | "ai" | "db" | "slack" | "errors";
export type Glyph = "table" | "router" | "search" | "target" | "browser" | "doc" | "database" | "hash" | "warning";

export const ACCENT = {
  glacier: "#2563eb",
  violet: "#7c5cf0",
  aurora: "#0f9f88",
  amber: "#d4900b",
  ember: "#e5484d",
} as const;

export const FLOW_NODES: Record<
  FlowNodeKey,
  { label: string; sub: string; pos: [number, number, number]; about: string; accent: string; glyph: Glyph; to: string; link: string }
> = {
  intake: {
    label: "Airtable",
    sub: "new client row",
    pos: [-5.8, 0, 0.3],
    about: "An account manager adds a row or fills in the form. Airtable calls the Make webhook straight away.",
    accent: ACCENT.glacier,
    glyph: "table",
    to: "/clients",
    link: "See the clients",
  },
  make: {
    label: "Make",
    sub: "router",
    pos: [-3.05, 0, 0.55],
    about: "The Make scenario sends the client down one branch for each service they bought.",
    accent: ACCENT.violet,
    glyph: "router",
    to: "/automations",
    link: "See the scenarios",
  },
  seo: {
    label: "SEO",
    sub: "checklist",
    pos: [-0.2, 2.3, -1.1],
    about: "SEO branch: creates the SEO kickoff checklist and posts a Slack welcome.",
    accent: ACCENT.aurora,
    glyph: "search",
    to: "/clients",
    link: "See the checklists",
  },
  ads: {
    label: "Paid Ads",
    sub: "checklist",
    pos: [-0.2, 0, 1.15],
    about: "Paid Ads branch: account access, tracking audit, campaign build and budget targets.",
    accent: ACCENT.aurora,
    glyph: "target",
    to: "/clients",
    link: "See the checklists",
  },
  web: {
    label: "Web Design",
    sub: "checklist",
    pos: [-0.2, -2.3, -1.1],
    about: "Web Design branch: kickoff call, brand assets, wireframes and staging checks.",
    accent: ACCENT.aurora,
    glyph: "browser",
    to: "/sites",
    link: "See the website drafts",
  },
  ai: {
    label: "AI brief",
    sub: "Python + LLM",
    pos: [2.65, 0, 0.45],
    about: "Python asks the model for a brief (audience, tone, three quick wins), saves it to Airtable and emails the account manager a draft.",
    accent: ACCENT.amber,
    glyph: "doc",
    to: "/clients",
    link: "Read a brief",
  },
  db: {
    label: "Supabase",
    sub: "reporting data",
    pos: [5.55, 1.35, -0.2],
    about: "A daily job upserts ad performance here and the dashboard reads it live.",
    accent: ACCENT.glacier,
    glyph: "database",
    to: "/reporting",
    link: "Open reporting",
  },
  slack: {
    label: "Slack",
    sub: "#northwind-ops",
    pos: [5.55, -1.1, -0.2],
    about: "Welcome messages, weekly summaries and failure alerts land in the ops channel.",
    accent: ACCENT.violet,
    glyph: "hash",
    to: "/automations",
    link: "See the alerts",
  },
  errors: {
    label: "Error route",
    sub: "log + alert",
    pos: [3.0, -2.55, 1.0],
    about: "Any step that fails is written to the automation log with its error, and a Slack alert names the run. Nothing fails silently.",
    accent: ACCENT.ember,
    glyph: "warning",
    to: "/automations",
    link: "Open the automation log",
  },
};

export const FLOW_EDGES: { from: FlowNodeKey; to: FlowNodeKey; error?: boolean }[] = [
  { from: "intake", to: "make" },
  { from: "make", to: "seo" },
  { from: "make", to: "ads" },
  { from: "make", to: "web" },
  { from: "seo", to: "ai" },
  { from: "ads", to: "ai" },
  { from: "web", to: "ai" },
  { from: "ai", to: "db" },
  { from: "ai", to: "slack" },
  { from: "ai", to: "errors", error: true },
  { from: "errors", to: "slack", error: true },
];

export type FlowSignal = { id: number; ok: boolean; branches: ("seo" | "ads" | "web")[] };

export const SERVICE_BRANCH: Record<string, "seo" | "ads" | "web"> = { SEO: "seo", "Paid Ads": "ads", "Web Design": "web" };
