// Tiny shared store: live API data plus the signals the 3D desk reacts to.
import { useSyncExternalStore } from "react";
import type { Account, CrmSummary, Draft, Lead, Report, Run, RunEvent, Status } from "./api";

export interface AgentState {
  status: Status | null;
  leads: Lead[];
  accounts: Account[];
  crm: CrmSummary | null;
  queue: Draft[];
  runs: Run[];
  report: Report | null;
  live: { runId: number; events: RunEvent[]; done: boolean } | null;
  beams: { tool: string; at: number }[];     // tool calls to light up on the desk
  sealed: { at: number; approved: boolean }[]; // approvals and rejections, for the letter stack
  focusLead: number | null;
  section: number;
  error: string | null;
}

let state: AgentState = {
  status: null, leads: [], accounts: [], crm: null, queue: [], runs: [], report: null, live: null,
  beams: [], sealed: [], focusLead: null, section: 0, error: null,
};

/** Scroll position as "section index + progress through it"; written by the page, read by the camera every frame. */
export const scroll = { progress: 0 };
const listeners = new Set<() => void>();

export const store = {
  get: () => state,
  set(patch: Partial<AgentState>) {
    state = { ...state, ...patch };
    listeners.forEach((l) => l());
  },
  subscribe(l: () => void) {
    listeners.add(l);
    return () => { listeners.delete(l); };
  },
  beam(tool: string) {
    const now = performance.now();
    store.set({ beams: [...state.beams.filter((b) => now - b.at < 4000), { tool, at: now }] });
  },
  seal(approved: boolean) {
    const now = performance.now();
    store.set({ sealed: [...state.sealed.filter((s) => now - s.at < 4000), { at: now, approved }] });
  },
};

export function useAgent<T>(select: (s: AgentState) => T): T {
  return useSyncExternalStore(store.subscribe, () => select(state));
}

export const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
