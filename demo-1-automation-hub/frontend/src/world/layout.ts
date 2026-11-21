import type { Alert, ChannelRow, Cube, Overview, TrendPoint } from "../lib/api";
import { ZONES, type Vec3 } from "./store";

/**
 * Where everything stands in the 3D world, as plain numbers. Pages import these to aim the camera
 * and place labels without loading three.js; the world's meshes use the same functions.
 */
export const SPEND = { x0: -9.3, dx: 0.64, z0: ZONES.spend[2] + 2.6, dz: 1.25, w: 0.46, d: 0.82, maxH: 3.4, ribbonZ: ZONES.spend[2] + 0.1 };
export const barX = (day: number) => ZONES.spend[0] + SPEND.x0 + day * SPEND.dx;
export const rowZ = (row: number) => SPEND.z0 - row * SPEND.dz;
export const barHeight = (spend: number, max: number) => 0.06 + (max > 0 ? spend / max : 0) * SPEND.maxH;
export type Band = "better" | "normal" | "watch" | "alert" | "none";
export function bandOf(cpa: number | null, median: number | null): Band {
  if (cpa == null || !median) return "none";
  const r = cpa / median;
  return r < 0.85 ? "better" : r > 1.6 ? "alert" : r > 1.25 ? "watch" : "normal";
}
export const sortedRows = (cube: Cube | null) => (cube ? [...cube.rows].sort((a, b) => b.total_spend - a.total_spend).slice(0, 8) : []);
/** Days that fall inside an open cost alert's week, per client, so the bars can show it. */
export function alertDays(cube: Cube | null, alerts: Alert[] | null) {
  const out = new Set<string>();
  if (!cube || !alerts) return out;
  for (const a of alerts) cube.dates.forEach((d, i) => d >= a.week.start && d <= a.week.end && out.add(`${a.client_id}:${i}`));
  return out;
}
/** Daily spend as a ribbon you can walk around: a glass curtain under a lit line, one bead per day. */
export function ribbonPoints(series: TrendPoint[]): Vec3[] {
  if (!series.length) return [];
  const vals = series.map((p) => p.spend);
  const lo = Math.min(...vals) * 0.96;
  const hi = Math.max(...vals) * 1.02;
  const n = series.length;
  return vals.map((v, i) => [barX((i * 29) / Math.max(1, n - 1)), SPEND.maxH + 1.1 + ((v - lo) / Math.max(1, hi - lo)) * 2.2, SPEND.ribbonZ]);
}
export const R0 = 2.0;
export const R1 = 3.3;
export function channelArcs(channels: ChannelRow[]) {
  const gap = 0.05;
  const first = channels[0]?.share_of_spend ?? 0;
  let a = -Math.PI / 2 - first * Math.PI;
  return channels.map((c, i) => {
    const span = Math.max(0.02, c.share_of_spend * Math.PI * 2 - gap);
    const arc = { name: c.channel, share: c.share_of_spend, a0: a, a1: a + span, h: 0.35 + c.share_of_spend * 1.7, i };
    a += span + gap;
    return { ...arc, mid: (arc.a0 + arc.a1) / 2 };
  });
}
export const arcLabelPos = (mid: number, h: number): Vec3 => [ZONES.channels[0] + Math.cos(mid) * (R1 + 0.55), h + 0.35, ZONES.channels[2] - Math.sin(mid) * (R1 + 0.55)];
export function pedestalPos(i: number, n: number): Vec3 {
  const off = i - (n - 1) / 2;
  return [ZONES.clients[0] + off * 2.3, 0, ZONES.clients[2] - off * off * 0.34];
}
export const pedestalHeight = (spend: number, max: number) => 0.55 + (max > 0 ? spend / max : 0) * 3.1;
export type ClientCol = Overview["clients"][number];
export const clientOrder = (clients: ClientCol[] | null) => [...(clients ?? [])].sort((a, b) => b.spend - a.spend).slice(0, 7);
export const RUN = { a: 5.8, b: 2.5, t0: Math.PI * 0.1, t1: Math.PI * 0.9, slots: 14 };
export const runPoint = (theta: number, y = 0): Vec3 => [ZONES.runs[0] + RUN.a * Math.cos(theta), y, ZONES.runs[2] + RUN.b * Math.sin(theta)];
export const slotTheta = (k: number, n: number) => {
  const step = (RUN.t1 - RUN.t0) / Math.max(n, 8);
  return (RUN.t1 + RUN.t0) / 2 + ((n - 1) / 2) * step - k * step;
};
export const SITE_KINDS = ["hero", "services", "proof", "cta"] as const;
export const slabY = (i: number) => 0.55 + (3 - i) * 0.68;
export const SLAB = { w: 3.8, d: 2.3 };
export const SITE_SECTIONS = SITE_KINDS;
export const SOCKETS = ["google", "meta", "ai", "airtable", "slack", "email", "database", "storage", "make"] as const;
export const socketPos = (i: number): Vec3 => {
  const row = i < 5 ? 0 : 1;
  const col = row === 0 ? i : i - 5;
  const perRow = row === 0 ? 5 : 4;
  return [ZONES.settings[0] + (col - (perRow - 1) / 2) * 1.75, 0.3, ZONES.settings[2] + (row - 0.5) * 1.7];
};
