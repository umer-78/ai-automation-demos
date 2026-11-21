// Where everything sits in the world, and where the camera goes for each page section.
import { Vector3 } from "three";

export const FOG = "#E7EDF1";
export const CORE = new Vector3(0, 2.15, 0);
export const CITY = new Vector3(0, 0, -27);
export const MONITOR = new Vector3(9.5, 3.4, -53);
export const RAIL = new Vector3(-7, 0, -72);

export interface Station { name: string; sub: string; color: string; pos: Vector3; core?: boolean; incoming?: boolean }

const ring = (deg: number, r = 5.6) => {
  const a = (deg * Math.PI) / 180;
  return new Vector3(Math.cos(a) * r, 0.55, Math.sin(a) * r + 0.3);
};

// Order matches hub.sendPackets: 0 Airtable, 1 Make, 2 the hub itself (Python + Claude), 3 Supabase, 4 Slack.
export const STATIONS: Station[] = [
  { name: "Airtable", sub: "Clients table", color: "#F2B134", pos: ring(196), incoming: true },
  { name: "Make", sub: "Webhook router", color: "#7B61FF", pos: ring(238), incoming: true },
  { name: "Hub API", sub: "Python and Claude", color: "#12968A", pos: CORE.clone(), core: true },
  { name: "Supabase", sub: "Database and storage", color: "#3ECF8E", pos: ring(302) },
  { name: "Slack", sub: "Welcome and alerts", color: "#E0457B", pos: ring(344) },
];

// One camera shot per page section: [camera position, look-at target].
export const SHOTS: [Vector3, Vector3][] = [
  [new Vector3(0, 6.2, 22), new Vector3(0, 1.6, -2)],           // hero: the whole hub
  [new Vector3(1.5, 13, 13), new Vector3(0.3, 0.6, -2.4)],       // onboarding: from above, to follow the packets
  [new Vector3(1.2, 16, -5), new Vector3(1.2, 1.2, -27)],       // reporting: over the data city
  [new Vector3(4.3, 4.2, -41), new Vector3(9.5, 3.4, -53)],     // website drafts: the monitor
  [new Vector3(-5.2, 10.5, -59), new Vector3(-7, 0.8, -72)],   // operations: the log rail
];

// Ground point under each shot's subject; the key light and its shadows follow it.
export const FOCUS = [
  new Vector3(0, 0, -1.5), new Vector3(0, 0, -2), new Vector3(0, 0, -27), new Vector3(9.5, 0, -53), new Vector3(-7, 0, -72),
];
