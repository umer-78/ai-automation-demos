import { useState, type FormEvent } from "react";
import { api, type SiteDraft } from "../api";
import { hub, useHub } from "../store";
import { refresh } from "../data";
import { cn } from "../lib/cn";
import { Button, ErrorNote, Field, Input, Panel, Part, Section, Select, TextArea, useAction } from "./kit";

const TONES = ["confident", "warm", "playful", "premium", "minimal", "bold"];
const SECTIONS: [string, string][] = [["hero", "Hero"], ["services", "Services"], ["proof", "Testimonials"], ["cta", "Call to action"]];
const sectionName = (s: string) => SECTIONS.find(([k]) => k === s)?.[1] ?? (s === "all" || s === "site" ? "Whole site" : s);
const previewOf = (siteId: string, version: number) => `./api/sites/${siteId}/preview?v=${version}`;

export function SiteBuilder() {
  const site = useHub((s) => s.site);
  const preview = useHub((s) => s.preview);
  const act = useAction();
  const [spec, setSpec] = useState({ business_name: "Fjord & Pine Dental", industry: "Family dental clinic", tone: "warm", colour: "#1F6F8B" });
  const [services, setServices] = useState(["Check-ups and cleaning", "Invisalign", "Same-day emergencies"]);
  const [section, setSection] = useState("hero");
  const [instructions, setInstructions] = useState("");

  const show = async (d: SiteDraft) => {
    const full = await api.site(d.site_id).catch(() => d);
    hub.set({ site: full, preview: previewOf(full.site_id, full.version) });
    hub.sendPackets(full.storage?.sent ? [2, 3] : [2]);
    void refresh("log");
  };

  const generate = async (e: FormEvent) => {
    e.preventDefault();
    const d = await act.run("generate", () => api.newSite({ ...spec, services: services.map((s) => s.trim()) }));
    if (d) await show(d);
  };
  const rewrite = async (e: FormEvent) => {
    e.preventDefault();
    if (!site) return;
    const d = await act.run("rewrite", () => api.regenerate(site.site_id, section, instructions.trim()));
    if (d) { await show(d); setInstructions(""); }
  };

  return (
    <Section id="sites" scene={3}>
      <Panel id="sites" busy={act.busy !== null} title="Draft a client website"
        intro="Claude writes a four-section site from a short brief. Rewrite one section and the rest stays exactly as it was. Every version is kept.">
        <form className="form" onSubmit={generate}>
          <div className="form-row">
            <Field label="Business name"><Input value={spec.business_name} onChange={(e) => setSpec({ ...spec, business_name: e.target.value })} required /></Field>
            <Field label="Industry"><Input value={spec.industry} onChange={(e) => setSpec({ ...spec, industry: e.target.value })} required /></Field>
          </div>
          <fieldset className="field">
            <legend className="field-label">Three services</legend>
            <div className="grid gap-2">
              {services.map((s, i) => (
                <Input key={i} aria-label={`Service ${i + 1}`} value={s} required
                  onChange={(e) => setServices(services.map((x, j) => (j === i ? e.target.value : x)))} />
              ))}
            </div>
          </fieldset>
          <div className="form-row">
            <Field label="Tone">
              <Select value={spec.tone} onChange={(e) => setSpec({ ...spec, tone: e.target.value })}>
                {TONES.map((t) => <option key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</option>)}
              </Select>
            </Field>
            <Field label="Brand colour">
              <span className="colour">
                <input type="color" aria-label="Pick brand colour" value={spec.colour} onChange={(e) => setSpec({ ...spec, colour: e.target.value })} />
                <Input value={spec.colour} onChange={(e) => setSpec({ ...spec, colour: e.target.value })} pattern="#[0-9a-fA-F]{6}" spellCheck={false} />
              </span>
            </Field>
          </div>
          <Button type="submit" busy={act.busy === "generate"}>{act.busy === "generate" ? "Writing the draft" : site ? "Start a new draft" : "Generate draft"}</Button>
        </form>
        <ErrorNote error={act.error} />

        {site && (
          <>
            <Part title={`${site.business_name}, version ${site.version}`}
              foot={site.storage?.sent ? "Saved to Supabase Storage." : "Kept in the hub's database. Supabase Storage isn't set up."}>
              <p className="small mt-1">Written by {site.engine}. The preview is on the screen beside this panel.</p>
              <p className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
                <a className="link" href={preview ?? previewOf(site.site_id, site.version)} target="_blank" rel="noopener">Open full preview</a>
                {site.storage?.url && <a className="link" href={site.storage.url} target="_blank" rel="noopener">Open stored HTML</a>}
              </p>
            </Part>

            <Part title="Rewrite one section">
              <form className="form" onSubmit={rewrite}>
                <Field label="Section">
                  <Select value={section} onChange={(e) => setSection(e.target.value)}>
                    {SECTIONS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                  </Select>
                </Field>
                <Field label="What should change" hint="Leave empty for a fresh take on the same brief.">
                  <TextArea rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)}
                    placeholder="Lead with same-day emergency appointments." />
                </Field>
                <Button type="submit" busy={act.busy === "rewrite"}>{act.busy === "rewrite" ? "Rewriting" : `Rewrite ${sectionName(section).toLowerCase()}`}</Button>
              </form>
            </Part>

            {site.versions && site.versions.length > 1 && (
              <Part title="Versions">
                <ol className="versions">
                  {site.versions.map((v) => {
                    const url = previewOf(site.site_id, v.version);
                    const on = preview === url;
                    return (
                      <li key={v.version} className={cn(on && "is-on")}>
                        <span>Version {v.version}: {v.version === 1 ? "whole site" : sectionName(v.section).toLowerCase()}</span>
                        <button type="button" className="link" aria-pressed={on} onClick={() => hub.set({ preview: url })}>{on ? "On screen" : "Show"}</button>
                      </li>
                    );
                  })}
                </ol>
              </Part>
            )}
          </>
        )}
      </Panel>
    </Section>
  );
}
