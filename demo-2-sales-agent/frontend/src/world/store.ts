import { useEffect, useRef, useSyncExternalStore } from "react";

export type Vec3 = [number, number, number];
export type Zone = "radar" | "agent" | "queue" | "crm" | "learning" | "report" | "settings";
/** A camera position, what it looks at, and how far the picture is shifted sideways to leave room for a panel. */
export type Shot = { pos: Vec3; target: Vec3; shift: number; zone: Zone };

/** Where each part of the world stands on the studio floor. */
export const ZONES: Record<Zone, Vec3> = {
  radar: [0, 0, 0],
  agent: [0, 0, -22],
  queue: [19, 0, -7],
  crm: [-19, 0, -7],
  learning: [-16, 0, 13],
  report: [16, 0, 13],
  settings: [0, 0, 20],
};

export const SHOTS = {
  home: { pos: [0.6, 12.5, 14.5], target: [0.4, 0.2, 0.4], shift: 0.2, zone: "radar" },
  leads: { pos: [-3.2, 9, 10.5], target: [-0.2, 0.4, 0], shift: -0.18, zone: "radar" },
  profile: { pos: [1, 15.5, 7.5], target: [0.2, 0, 0.2], shift: 0.21, zone: "radar" },
  agent: { pos: [0, 10, -8.5], target: [0, 0.6, -22.4], shift: 0.19, zone: "agent" },
  runs: { pos: [7, 12.5, -7.5], target: [0.4, 0.6, -22], shift: -0.16, zone: "agent" },
  queue: { pos: [19, 8.6, 4.2], target: [19, 0.7, -7.2], shift: 0.19, zone: "queue" },
  crm: { pos: [-19, 11.2, 5.6], target: [-19, 0.6, -7.6], shift: 0.19, zone: "crm" },
  learning: { pos: [-16, 5.8, 23.5], target: [-16, 1.9, 13], shift: 0.2, zone: "learning" },
  report: { pos: [16, 5.8, 23.5], target: [16, 2, 13], shift: 0.2, zone: "report" },
  settings: { pos: [0, 10.5, 35], target: [-0.9, 0.3, 20], shift: 0.2, zone: "settings" },
} satisfies Record<string, Shot>;
export type ShotName = keyof typeof SHOTS;

type State = {
  shot: ShotName;
  /** A one-off camera target that overrides the shot (a selected account, say). */
  focus: Shot | null;
  /** The lead or account under the pointer, and the one opened on the page. */
  hoverLead: number | null;
  lead: number | null;
  hoverAccount: number | null;
  account: number | null;
  /** The account flag the CRM page filters by; the pillars follow it. */
  flag: string | null;
  /** The approval tab on screen, so the matching tray lifts. */
  tray: "pending" | "approved" | "rejected" | "sent" | null;
};

let state: State = { shot: "home", focus: null, hoverLead: null, lead: null, hoverAccount: null, account: null, flag: null, tray: null };
const subs = new Set<() => void>();

export const world = {
  get: () => state,
  set(patch: Partial<State>) {
    state = { ...state, ...patch };
    subs.forEach((fn) => fn());
  },
  subscribe(fn: () => void) {
    subs.add(fn);
    return () => void subs.delete(fn);
  },
};

export function useWorld<T>(select: (s: State) => T): T {
  return useSyncExternalStore(world.subscribe, () => select(world.get()));
}

/**
 * A page section that takes the camera to its shot when it reaches the middle of the screen.
 * Scrolling the page therefore flies the camera from one part of the world to the next.
 */
export function useSectionShot<T extends HTMLElement>(shot: ShotName, focus: Shot | null = null) {
  const ref = useRef<T>(null);
  const focusRef = useRef(focus);
  const active = useRef(false);
  focusRef.current = focus;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        const hit = entries.some((e) => e.isIntersecting);
        active.current = hit;
        if (hit) world.set({ shot, focus: focusRef.current });
      },
      { rootMargin: "-48% 0px -48% 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [shot]);
  const key = focus ? `${focus.pos.join(",")}|${focus.target.join(",")}` : "";
  useEffect(() => {
    if (active.current && focusRef.current) world.set({ shot, focus: focusRef.current });
  }, [key, shot]);
  return ref;
}
