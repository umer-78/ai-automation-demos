import { useEffect, useRef, useSyncExternalStore } from "react";
import type { FlowNodeKey, FlowSignal } from "../components/flowNodes";

export type Vec3 = [number, number, number];
export type Zone = "flow" | "spend" | "channels" | "clients" | "sites" | "runs" | "settings";
/** A camera position, what it looks at, and how far the picture is shifted sideways to leave room for a panel. */
export type Shot = { pos: Vec3; target: Vec3; shift: number; zone: Zone };

/** Where each part of the world stands on the studio floor. */
export const ZONES: Record<Zone, Vec3> = {
  flow: [0, 0, 0],
  spend: [0, 0, -26],
  channels: [17, 0, -8],
  clients: [-17, 0, -8],
  sites: [-15, 0, 9],
  runs: [15, 0, 9],
  settings: [0, 0, 17],
};

export const SHOTS = {
  home: { pos: [-0.2, 15, 22.6], target: [-0.4, 0.2, 0.6], shift: 0.21, zone: "flow" },
  metrics: { pos: [15.5, 14.5, -3.5], target: [-0.5, 1.8, -25.8], shift: 0.15, zone: "spend" },
  alert: { pos: [12.5, 7, -14.5], target: [6.5, 1.2, -23.4], shift: -0.17, zone: "spend" },
  channels: { pos: [17, 9.6, 4.6], target: [17, 0.3, -8], shift: 0.17, zone: "channels" },
  runs: { pos: [15, 14.5, 28.5], target: [15, 0.3, 10.4], shift: -0.12, zone: "runs" },
  clients: { pos: [-17, 8.2, 6.5], target: [-17, 1.4, -8.6], shift: 0.17, zone: "clients" },
  reporting: { pos: [-13, 18, -6], target: [0, 1, -26], shift: 0.12, zone: "spend" },
  sites: { pos: [-15, 7.4, 21], target: [-15, 1.6, 9], shift: 0.17, zone: "sites" },
  automation: { pos: [12, 11, 14], target: [0, 0.2, 0.2], shift: -0.15, zone: "flow" },
  settings: { pos: [0, 10.5, 32.5], target: [-0.9, 0.3, 17], shift: 0.2, zone: "settings" },
} satisfies Record<string, Shot>;
export type ShotName = keyof typeof SHOTS;

type State = {
  shot: ShotName;
  /** A one-off camera target that overrides the shot (a selected client, say). */
  focus: Shot | null;
  signal: FlowSignal | null;
  step: FlowNodeKey | null;
  hoveredStep: FlowNodeKey | null;
  hoverBar: { row: number; day: number } | null;
  focusClient: number | null;
  /** Reporting's client filter, which the spend landscape, ribbon and ring follow. */
  clientId: number | null;
  /** The site draft shown as slabs, and the section being pointed at or just rewritten. */
  draftId: string | null;
  slab: string | null;
  slabFlash: string | null;
};

let state: State = { shot: "home", focus: null, signal: null, step: null, hoveredStep: null, hoverBar: null, focusClient: null, clientId: null, draftId: null, slab: null, slabFlash: null };
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

/** Select one primitive or stable value from the world state. */
export function useWorld<T>(select: (s: State) => T): T {
  return useSyncExternalStore(world.subscribe, () => select(world.get()));
}

/** Send a run through the workflow model; branches are the services the client bought. */
export function sendRun(ok: boolean, branches: FlowSignal["branches"]) {
  world.set({ signal: { id: (state.signal?.id ?? 0) + 1, ok, branches: branches.length ? branches : ["ads"] } });
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
  // data that arrives after the section is on screen still moves the camera
  const key = focus ? `${focus.pos.join(",")}|${focus.target.join(",")}` : "";
  useEffect(() => {
    if (active.current && focusRef.current) world.set({ shot, focus: focusRef.current });
  }, [key, shot]);
  return ref;
}
