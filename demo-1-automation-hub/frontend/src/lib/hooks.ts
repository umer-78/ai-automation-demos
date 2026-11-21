import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Status } from "./api";
import { setCurrency } from "./format";

/** When the dashboard last heard from the API; the header shows it as a live status. */
let lastSync = 0;
let syncFailed = false;
const syncListeners = new Set<() => void>();
function markSync(ok: boolean) {
  if (ok) lastSync = Date.now();
  syncFailed = !ok;
  syncListeners.forEach((fn) => fn());
}
export function useSyncStatus() {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    syncListeners.add(fn);
    const tick = window.setInterval(fn, 1000);
    return () => {
      syncListeners.delete(fn);
      window.clearInterval(tick);
    };
  }, []);
  return { lastSync, failed: syncFailed };
}

export function useApi<T>(path: string | null, refreshMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const mounted = useRef(true);

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const result = await api.get<T>(path);
      markSync(true);
      if (mounted.current) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      markSync(false);
      if (mounted.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    mounted.current = true;
    setLoading(Boolean(path));
    void load();
    if (!refreshMs) return () => void (mounted.current = false);
    const id = window.setInterval(() => void load(), refreshMs);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
    };
  }, [load, path, refreshMs]);

  return { data, error, loading, reload: load, setData };
}

export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/** Re-renders listeners when any action changes server data (simple app-wide refresh signal). */
const listeners = new Set<() => void>();
export const dataChanged = () => listeners.forEach((fn) => fn());
export function useOnDataChanged(fn: () => void) {
  useEffect(() => {
    listeners.add(fn);
    return () => void listeners.delete(fn);
  }, [fn]);
}

/** Server status: demo or real data, which accounts feed it, when it last synced. Shared by the header and pages. */
let statusCache: Status | null = null;
const statusListeners = new Set<() => void>();
let statusTimer = 0;
async function loadStatus() {
  try {
    statusCache = await api.get<Status>("/api/status");
    if (statusCache.data?.currency) setCurrency(statusCache.data.currency);
  } catch {
    /* the header shows the API as reconnecting */
  }
  statusListeners.forEach((fn) => fn());
}
export function refreshStatus() {
  void loadStatus();
}
export function useStatus(): Status | null {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    statusListeners.add(fn);
    if (!statusTimer) {
      void loadStatus();
      statusTimer = window.setInterval(() => void loadStatus(), 30000);
    }
    return () => void statusListeners.delete(fn);
  }, []);
  return statusCache;
}
