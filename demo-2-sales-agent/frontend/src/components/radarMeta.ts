/** Shared with the overview legend; kept out of LeadRadar.tsx so three.js stays in its own chunk. */
export const QUADRANTS = [
  { key: "compliance", label: "Compliance milestones", start: 0, corner: "top-right" },
  { key: "security_leader", label: "New security leaders", start: Math.PI / 2, corner: "top-left" },
  { key: "funding", label: "Funding", start: Math.PI, corner: "bottom-left" },
  { key: "other", label: "Hiring, expansion, other", start: (3 * Math.PI) / 2, corner: "bottom-right" },
] as const;
