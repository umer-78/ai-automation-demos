import { useEffect } from "react";
import { api, type RunEvent } from "./api";
import { store, type AgentState } from "./store";

type Key = "status" | "leads" | "accounts" | "queue" | "runs" | "report";
const loaders: Record<Key, () => Promise<Partial<AgentState>>> = {
  status: async () => ({ status: await api.status() }),
  leads: async () => ({ leads: await api.leads() }),
  accounts: async () => {
    const r = await api.accounts();
    return { accounts: r.accounts, crm: r.summary };
  },
  queue: async () => ({ queue: await api.drafts() }),
  runs: async () => ({ runs: await api.runs() }),
  report: async () => ({ report: await api.report() }),
};

/** Reload parts of the shared state from the API. */
export async function refresh(...keys: Key[]) {
  const results = await Promise.allSettled(keys.map((k) => loaders[k]()));
  let patch: Partial<AgentState> = {};
  let error: string | null = null;
  for (const r of results) {
    if (r.status === "fulfilled") patch = { ...patch, ...r.value };
    else error = r.reason instanceof Error ? r.reason.message : String(r.reason);
  }
  store.set({ ...patch, error });
}

export const refreshAll = () => refresh("status", "leads", "accounts", "queue", "runs", "report");

let source: EventSource | null = null;
let pending = 0;

/** Follow a run live: each tool call arrives as a server-sent event and lights up the desk. */
export function follow(runId: number) {
  source?.close();
  store.set({ live: { runId, events: [], done: false } });
  source = new EventSource(`./api/agent/runs/${runId}/events`);
  source.onmessage = (msg) => {
    const e = JSON.parse(msg.data) as RunEvent;
    const live = store.get().live;
    if (!live || live.runId !== runId || live.events.some((x) => x.seq === e.seq)) return;
    store.set({ live: { ...live, events: [...live.events, e] } });
    if (e.tool) store.beam(e.tool);
    // Pull fresh lists while the run works, at most every 700 ms.
    if (e.tool && ["save_lead", "create_draft", "recommend_followup", "score_accounts"].includes(e.tool)) {
      window.clearTimeout(pending);
      pending = window.setTimeout(() => void refresh("leads", "queue", "accounts"), 700);
    }
  };
  source.addEventListener("end", () => {
    source?.close();
    source = null;
    const live = store.get().live;
    if (live) store.set({ live: { ...live, done: true } });
    void refreshAll();
  });
}

/** First load, then follow a run that's already going (for example after a reload). */
export function useBoot() {
  useEffect(() => {
    void (async () => {
      await refreshAll();
      const running = store.get().status?.running_run;
      if (running) follow(running);
    })();
    const t = setInterval(() => { if (!document.hidden && !source) void refresh("status"); }, 45000);
    return () => { clearInterval(t); source?.close(); };
  }, []);
}
