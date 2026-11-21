import { api, ApiError } from "./api";
import { follow, refresh } from "./data";
import { store } from "./store";

/** Start a run and follow it live. If one is already going, follow that one instead. */
export async function startRun(): Promise<string | null> {
  try {
    const { run_id } = await api.run();
    follow(run_id);
    void refresh("status", "runs");
    return null;
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      await refresh("status");
      const running = store.get().status?.running_run;
      if (running) follow(running);
      return null;
    }
    return e instanceof Error ? e.message : String(e);
  }
}

export const goTo = (id: string) =>
  document.getElementById(id)?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
