import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, PREVIEW, type LiveStep, type Run } from "./api";
import { dataChanged } from "./hooks";

type RunState = {
  run: Run | null;
  busy: boolean;
  error: string | null;
  start: () => Promise<void>;
  watch: (id: string) => void;
};

const Ctx = createContext<RunState | null>(null);

/** One agent run at a time, shared by the header button, the overview and the run log. */
export function RunProvider({ children }: { children: ReactNode }) {
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const timer = useRef<number | null>(null);

  const poll = useCallback(async (id: string) => {
    try {
      const next = await api.get<Run>(`/api/runs/${id}`);
      setRun(next);
      if (next.status === "running") {
        timer.current = window.setTimeout(() => void poll(id), 700);
      } else {
        dataChanged();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (!runId) return;
    void poll(runId);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [runId, poll]);

  const watch = useCallback((id: string) => setRunId((current) => (current === id ? current : id)), []);

  // hosted preview: "Run agent" plays back the last real run step by step, the way a live run looks
  const replay = useCallback(async () => {
    const overview = await api.get<{ latest_run: Run | null }>("/api/overview").catch(() => null);
    if (!overview?.latest_run) return;
    const full = await api.get<Run>(`/api/runs/${overview.latest_run.id}`);
    const steps: LiveStep[] = (full.tools_called ?? []).map((t) => ({ step: t.tool, at_ms: t.at_ms, ok: t.ok, via: t.via, result: t.result }));
    const running: Run = { ...full, status: "running", tools_called: undefined, live_steps: [], summary: null, outcome: null };
    let shown = 0;
    setRun(running);
    if (timer.current) window.clearTimeout(timer.current);
    const tick = () => {
      shown += 1;
      if (shown > steps.length) {
        setRun(full);
        dataChanged();
        return;
      }
      setRun({ ...running, live_steps: steps.slice(0, shown) });
      timer.current = window.setTimeout(tick, 130);
    };
    timer.current = window.setTimeout(tick, 400);
  }, []);

  const start = useCallback(async () => {
    if (PREVIEW) return replay();
    setStarting(true);
    setError(null);
    try {
      const res = await api.post<{ run_id: string }>("/api/agent/run");
      setRun(null);
      setRunId(res.run_id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const overview = await api.get<{ running: string | null }>("/api/overview").catch(() => null);
        if (overview?.running) {
          setRunId(overview.running);
          setError("A run is already in progress. Showing it now.");
        } else {
          setError(e.message);
        }
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setStarting(false);
    }
  }, [replay]);

  // a run we were told about but have not loaded yet still counts as running, so the button
  // never flips back to "Run agent" between the start request and the first status check
  const awaitingFirstLook = runId !== null && run?.id !== runId && !error;
  const busy = starting || awaitingFirstLook || run?.status === "running";
  return <Ctx.Provider value={{ run, busy, error, start, watch }}>{children}</Ctx.Provider>;
}

export function useRun() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useRun must be used inside RunProvider");
  return ctx;
}
