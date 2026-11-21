import { useEffect } from "react";
import { api } from "./api";
import { hub, type HubState } from "./store";

type Key = "status" | "dashboard" | "clients" | "log";
const loaders: Record<Key, () => Promise<unknown>> = {
  status: api.status, dashboard: api.dashboard, clients: api.clients, log: () => api.log(30),
};

/** Reload parts of the shared state from the API. */
export async function refresh(...keys: Key[]) {
  const results = await Promise.allSettled(keys.map((k) => loaders[k]()));
  const patch: Record<string, unknown> = {};
  let error: string | null = null;
  results.forEach((r, i) => {
    if (r.status === "fulfilled") patch[keys[i]] = r.value;
    else error = r.reason instanceof Error ? r.reason.message : String(r.reason);
  });
  hub.set({ ...(patch as Partial<HubState>), error });
}

export const refreshAll = () => refresh("status", "dashboard", "clients", "log");

/** First load, then light polling of the activity log while the tab is visible. */
export function useBoot() {
  useEffect(() => {
    void refreshAll();
    const log = setInterval(() => { if (!document.hidden) void refresh("log"); }, 12000);
    const status = setInterval(() => { if (!document.hidden) void refresh("status"); }, 60000);
    return () => { clearInterval(log); clearInterval(status); };
  }, []);
}
