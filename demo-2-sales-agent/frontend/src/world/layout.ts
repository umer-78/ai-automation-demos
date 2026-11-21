/** Where things stand in the world. Pure numbers, shared by the 3D zones and the labels that float over them. */
import { QUADRANTS } from "../components/radarMeta";
import { STATIONS, type StationKey } from "../components/flowMeta";
import type { LeadCard } from "../lib/api";
import { ZONES, type Vec3 } from "./store";

// ------------------------------------------------------------------ radar
export const DISH_R = 5.4;
/** Scores of 95+ sit near the centre, 35 and below on the rim. */
export const ringRadius = (score: number) => 0.7 + (DISH_R - 1.05) * Math.min(1, Math.max(0, (95 - score) / 60));
export const pinHeight = (score: number) => 0.3 + Math.max(0, score - 30) / 70 * 1.45;

function hash(n: number) {
  const x = Math.sin(n * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}
const quadrantOf = (signal: string | null) => QUADRANTS.find((q) => q.key === signal) ?? QUADRANTS[3];

export function placeLead(lead: LeadCard) {
  const q = quadrantOf(lead.signal);
  const theta = q.start + (0.12 + 0.76 * hash(lead.id)) * (Math.PI / 2);
  const r = ringRadius(lead.score);
  return { x: r * Math.cos(theta), z: -r * Math.sin(theta), theta };
}
export function leadTop(lead: LeadCard): Vec3 {
  const { x, z } = placeLead(lead);
  return [ZONES.radar[0] + x, 0.39 + pinHeight(lead.score) + 0.36, ZONES.radar[2] + z];
}

// ------------------------------------------------------------------ agent track (local to the zone)
export const STATION_POS: Record<StationKey, [number, number]> = Object.fromEntries(STATIONS.map((s) => [s.key, [s.pos[0] * 1.42, s.pos[1] * 1.5 - 0.2]])) as Record<StationKey, [number, number]>;
export const GATE_POS: [number, number] = [STATION_POS.draft[0] + 1.25, 2.45];
const KEYS = STATIONS.map((s) => s.key);
/** How far along the track (0 to 1) the bead sits when station `i` is reached. */
export const stationU = (i: number) => (KEYS.length > 1 ? Math.max(0, Math.min(1, i / (KEYS.length - 1))) : 0);
export const stationTop = (k: StationKey): Vec3 => [ZONES.agent[0] + STATION_POS[k][0], 1.55, ZONES.agent[2] + STATION_POS[k][1]];
export const gateTop = (): Vec3 => [ZONES.agent[0] + GATE_POS[0], 1.9, ZONES.agent[2] + GATE_POS[1]];

// ------------------------------------------------------------------ approval trays (local)
export const TRAYS = ["pending", "approved", "rejected", "sent"] as const;
export type TrayKey = (typeof TRAYS)[number];
export const trayPos = (k: TrayKey): [number, number] => {
  const i = TRAYS.indexOf(k);
  return [(i % 2 === 0 ? -1.45 : 1.45), i < 2 ? -1.2 : 1.2];
};
export const trayTop = (k: TrayKey, count: number): Vec3 => {
  const [x, z] = trayPos(k);
  return [ZONES.queue[0] + x, 0.55 + Math.min(count, 14) * 0.062, ZONES.queue[2] + z];
};

// ------------------------------------------------------------------ CRM pillars (local)
const COLS = 10;
export const accountPos = (i: number): [number, number] => [((i % COLS) - (COLS - 1) / 2) * 1.08, (Math.floor(i / COLS) - 2.5) * 1.1];
export const accountTop = (i: number, h: number): Vec3 => {
  const [x, z] = accountPos(i);
  return [ZONES.crm[0] + x, h + 0.45, ZONES.crm[2] + z];
};

// ------------------------------------------------------------------ settings sockets (absolute)
export const SOCKETS = ["company", "ai", "research", "crm", "slack", "database"] as const;
export const socketPos = (i: number): Vec3 => {
  const row = i < 3 ? 0 : 1;
  const col = i % 3;
  return [ZONES.settings[0] + (col - 1) * 2.4, 0.3, ZONES.settings[2] + (row - 0.5) * 1.7];
};
