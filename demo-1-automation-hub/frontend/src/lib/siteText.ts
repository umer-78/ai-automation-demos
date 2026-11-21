import type { SiteDraft } from "./api";

export type SectionKey = "hero" | "services" | "proof" | "cta";
export const SECTION_LABEL: Record<SectionKey, string> = { hero: "Hero", services: "Services", proof: "Proof", cta: "Call to action" };

function parse(html: string | undefined) {
  const doc = new DOMParser().parseFromString(`<div>${html ?? ""}</div>`, "text/html");
  const one = (sel: string) => doc.querySelector(sel)?.textContent?.trim() ?? "";
  const many = (sel: string) => Array.from(doc.querySelectorAll(sel), (n) => n.textContent?.trim() ?? "").filter(Boolean);
  return { one, many };
}

/** Plain text pulled from each section of a draft, for the 3D slabs and the list beside them. */
export function sectionText(draft: SiteDraft | null) {
  const s = draft?.sections;
  const hero = parse(s?.hero);
  const services = parse(s?.services);
  const proof = parse(s?.proof);
  const cta = parse(s?.cta);
  return {
    hero: { title: hero.one("h1") || hero.one("h2"), button: hero.one(".btn"), pills: hero.many(".pill").slice(0, 3) },
    services: { title: services.one("h2"), cards: services.many("h3").slice(0, 3) },
    proof: { title: proof.one("h2"), stats: proof.many(".stat-label").slice(0, 3) },
    cta: { title: cta.one("h2"), button: cta.one(".btn") },
  };
}
