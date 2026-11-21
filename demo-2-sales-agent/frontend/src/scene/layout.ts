// Where everything sits on the desk, and where the camera goes for each page section.
import { Vector3 } from "three";

export const BG = "#12302B";
export const TABLE_R = 9;
export const CORE = new Vector3(0, 2.5, 0);

// One token per agent tool, in the order a run uses them.
export const TOOLS = ["read_business_notes", "save_icp", "web_search", "save_lead", "read_crm", "score_accounts",
  "create_draft", "recommend_followup", "write_report"];
export const TOOL_POS = TOOLS.map((_, i) => {
  const a = (i / TOOLS.length) * Math.PI * 2 + Math.PI / 2;
  return new Vector3(Math.cos(a) * 3.3, 1.15, Math.sin(a) * 3.3);
});

/** Polar position on the table top: angle in degrees (90 = towards the viewer), radius from the centre. */
export const onTable = (deg: number, r: number, y = 0.31) => {
  const a = (deg * Math.PI) / 180;
  return new Vector3(Math.cos(a) * r, y, Math.sin(a) * r);
};

export const LEAD_ARC = { from: 228, to: 312, r: 6.3, row: 0.85 }; // behind the agent, two rows
export const CRM_LANES = { from: 108, to: 172, r0: 5.0, step: 0.9 }; // front left, one lane per stage
export const LETTERS = onTable(38, 6.3);                            // front right

// One camera shot per page section: [camera position, look-at target].
export const SHOTS: [Vector3, Vector3][] = [
  [new Vector3(0, 13.5, 26), new Vector3(0, 1.0, 0)],       // hero: the whole desk, set back
  [new Vector3(0.8, 8.2, 12.5), new Vector3(0, 1.9, 0)],    // run: the agent and its nine tools
  [new Vector3(0, 12.5, 5.5), new Vector3(0, 0.6, -5.0)],   // leads: over the pins
  [new Vector3(-8.5, 9.5, 11), new Vector3(-4.6, 0.3, 3.4)], // CRM: over the lanes
  [new Vector3(8.6, 5.6, 10.2), new Vector3(4.9, 0.6, 3.8)], // approvals: the letter stack
  [new Vector3(0, 21, 9), new Vector3(0, 0, 0)],            // report: the whole desk from above
];
export const FOCUS = SHOTS.map(([, look]) => new Vector3(look.x, 0, look.z));
