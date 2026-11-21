// Tiny shared store: live API data plus the signals the 3D scene reacts to.
import { useSyncExternalStore } from "react";
import type { Dashboard, LogRow, SiteDraft, Status, Client } from "./api";

export interface HubState {
  status: Status | null;
  dashboard: Dashboard | null;
  clients: Client[];
  log: LogRow[];
  site: SiteDraft | null;
  preview: string | null;            // URL of the site version shown on the 3D monitor
  focusClient: string | null;        // highlighted tower group in the data city
  pulse: { station: number; at: number }[]; // packets to send along the tubes (station index, time)
  section: number;                   // which section is on screen
  error: string | null;
}

let state: HubState = { status: null, dashboard: null, clients: [], log: [], site: null, preview: null, focusClient: null, pulse: [], section: 0, error: null };

/** Scroll position as "section index + progress through it"; written by the page, read by the camera every frame. */
export const scroll = { progress: 0 };
const listeners = new Set<() => void>();

export const hub = {
  get: () => state,
  set(patch: Partial<HubState>) {
    state = { ...state, ...patch };
    listeners.forEach((l) => l());
  },
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  /** Fire packets at the tool stations in order (0 Airtable, 1 Make, 2 the hub: Python + Claude, 3 Supabase, 4 Slack). */
  sendPackets(stations: number[]) {
    const now = performance.now();
    hub.set({ pulse: [...state.pulse.filter((p) => now - p.at < 6000), ...stations.map((s, i) => ({ station: s, at: now + i * 450 }))] });
  },
};

export function useHub<T>(select: (s: HubState) => T): T {
  return useSyncExternalStore(hub.subscribe, () => select(state), () => select(state));
}

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
