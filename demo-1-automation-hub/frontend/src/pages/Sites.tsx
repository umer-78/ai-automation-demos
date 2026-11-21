import clsx from "clsx";
import { ExternalLink, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { sectionText, type SectionKey } from "../lib/siteText";
import { Card, CardTitle, Section, btn } from "../world/Section";
import { world } from "../world/store";
import { Button, ErrorNote, Field, Pill, useToast } from "../components/ui";
import { api, type SiteDraft } from "../lib/api";
import { timeAgo } from "../lib/format";
import { dataChanged, useApi } from "../lib/hooks";

const SECTIONS: { key: keyof SiteDraft["sections"]; label: string }[] = [
  { key: "hero", label: "Hero" },
  { key: "services", label: "Services" },
  { key: "proof", label: "Proof" },
  { key: "cta", label: "Call to action" },
];
const TONES = ["Friendly and local", "Premium", "Bold and energetic", "Professional"];
const SWATCHES = ["teal", "navy", "forest green", "coral", "violet", "#b7791f"];

const START = { business_name: "", industry: "", tone: TONES[0], services: ["", "", ""], colour: "teal" };

export default function Sites() {
  const toast = useToast();
  const drafts = useApi<SiteDraft[]>("/api/sites");
  const [form, setForm] = useState(START);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [current, setCurrent] = useState<SiteDraft | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [regen, setRegen] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [hover, setHover] = useState<SectionKey | null>(null);
  const [changed, setChanged] = useState<SectionKey | null>(null);
  const [anchor, setAnchor] = useState("");
  const text = useMemo(() => sectionText(current), [current]);
  const titles: Record<SectionKey, string> = { hero: text.hero.title, services: text.services.title, proof: text.proof.title, cta: text.cta.title };

  useEffect(() => {
    if (!current && drafts.data?.length) {
      setCurrent(drafts.data[0]);
      setVersion(drafts.data[0].version);
    }
  }, [drafts.data, current]);

  async function generate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const d = await api.post<SiteDraft>("/api/sites", form);
      setCurrent({ ...d, versions: [{ version: 1, changed_section: null, created_at: d.created_at, html_url: d.html_url }] });
      setVersion(1);
      setAnchor("");
      toast("success", `Draft for ${d.business_name} is ready.`);
      void drafts.reload();
      dataChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function regenerate(section: string) {
    if (!current) return;
    setRegen(section);
    try {
      const d = await api.post<SiteDraft>(`/api/sites/${current.group_id}/regenerate`, { section, instruction });
      const versions = [...(current.versions ?? []), { version: d.version, changed_section: section, created_at: d.created_at, html_url: d.html_url }];
      setChanged(section as SectionKey);
      window.setTimeout(() => setChanged((c) => (c === section ? null : c)), 2600);
      setCurrent({ ...d, versions });
      setVersion(d.version);
      setAnchor(`#${section}`);
      setInstruction("");
      toast("success", `Rewrote the ${SECTIONS.find((s) => s.key === section)?.label.toLowerCase()} section. The other sections did not change.`);
      void drafts.reload();
    } catch (err) {
      toast("failure", err instanceof Error ? err.message : String(err));
    } finally {
      setRegen(null);
    }
  }

  // the slabs in the world show the draft picked here
  useEffect(() => {
    if (current) world.set({ draftId: current.group_id });
  }, [current]);
  useEffect(() => () => world.set({ draftId: null, slab: null }), []);
  useEffect(() => {
    world.set({ slab: hover });
  }, [hover]);
  useEffect(() => {
    if (changed) world.set({ slabFlash: changed });
  }, [changed]);

  const previewSrc = current ? api.url(`/sites/${current.group_id}/preview?v=${version ?? current.version}`) : null;

  return (
    <>
      <Section shot="sites">
        <Card>
          <CardTitle>Website drafts</CardTitle>
          <p className="mb-4 text-[15px] leading-relaxed text-[#3f444c]">Five answers in, a one-page site out: hero, services, proof and a call to action. Each slab beside this is one section of the latest draft.</p>
          <form onSubmit={generate} className="space-y-3.5">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Business name">
                <input required minLength={2} maxLength={80} className="field" value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} placeholder="Bloom & Co" />
              </Field>
              <Field label="Industry">
                <input required minLength={2} maxLength={80} className="field" value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} placeholder="Florist" />
              </Field>
            </div>
            <Field label="Tone">
              <select className="field" value={form.tone} onChange={(e) => setForm({ ...form, tone: e.target.value })}>
                {TONES.map((t) => <option key={t}>{t}</option>)}
              </select>
            </Field>
            <fieldset className="grid grid-cols-3 gap-2">
              <legend className="mb-1.5 text-[13.5px] font-medium">Three services</legend>
              {form.services.map((sv, i) => (
                <input
                  key={i}
                  required
                  minLength={2}
                  maxLength={60}
                  aria-label={`Service ${i + 1}`}
                  className="field"
                  value={sv}
                  placeholder={["Weddings", "Same-day delivery", "Workshops"][i]}
                  onChange={(e) => setForm({ ...form, services: form.services.map((x, j) => (j === i ? e.target.value : x)) })}
                />
              ))}
            </fieldset>
            <Field label="Colour" hint="A colour name or a hex code">
              <div className="flex flex-wrap items-center gap-1.5">
                <input required minLength={2} maxLength={40} className="field !w-36" value={form.colour} onChange={(e) => setForm({ ...form, colour: e.target.value })} />
                {SWATCHES.map((c) => (
                  <button type="button" key={c} onClick={() => setForm({ ...form, colour: c })} className={clsx("rounded-full px-2.5 py-1 text-[12.5px] ring-1", form.colour === c ? "bg-black text-white ring-black" : "text-[#5B616B] ring-black/10 hover:text-black")}>
                    {c}
                  </button>
                ))}
              </div>
            </Field>
            {error && <ErrorNote message={error} />}
            <button type="submit" className={clsx(btn.primary, "w-full")} disabled={busy}>
              {busy ? "Writing the draft…" : "Generate draft"}
            </button>
          </form>
        </Card>
      </Section>

      <Section shot="sites" side="right">
        <Card>
          <CardTitle aside={current && previewSrc ? <a href={previewSrc} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-black hover:underline">Open the page <ExternalLink className="size-3.5" /></a> : undefined}>
            {current ? current.business_name : "No draft yet"}
          </CardTitle>
          <p className="text-[14px] text-[#5B616B]">Point at a section to lift its slab. Rewrite changes only that section; the other three are copied into the new version unchanged.</p>
          <input
            className="field mt-3 !py-1.5 text-[13.5px]"
            placeholder="Optional instruction, e.g. shorter and warmer"
            aria-label="Instruction for the rewrite"
            value={instruction}
            maxLength={300}
            disabled={!current}
            onChange={(e) => setInstruction(e.target.value)}
          />
          <ul className="mt-2 divide-y divide-black/[0.07]">
            {SECTIONS.map((sec) => (
              <li key={sec.key} onMouseEnter={() => setHover(sec.key)} onMouseLeave={() => setHover(null)} className={clsx("-mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors", hover === sec.key && "bg-black/[0.04]")}>
                <span className={clsx("size-2 shrink-0 rounded-full", changed === sec.key ? "bg-[#0f9f88]" : "bg-black/20")} />
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-medium">{sec.label}</div>
                  <div className="truncate text-[13px] text-[#5B616B]">{current ? titles[sec.key] || "No heading" : "Not written yet"}</div>
                </div>
                <Button size="sm" icon={<RotateCcw className="size-3.5" />} busy={regen === sec.key} disabled={!current || Boolean(regen)} onClick={() => regenerate(sec.key)}>
                  Rewrite
                </Button>
              </li>
            ))}
          </ul>
          {current?.versions && current.versions.length > 1 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[13px]">
              <span className="text-[#5B616B]">Versions</span>
              {current.versions.map((v) => (
                <button key={v.version} onClick={() => setVersion(v.version)} className={clsx("rounded-full px-2.5 py-0.5 ring-1", (version ?? current.version) === v.version ? "bg-black text-white ring-black" : "text-[#5B616B] ring-black/10")}>
                  v{v.version}
                  {v.changed_section ? ` ${v.changed_section}` : ""}
                </button>
              ))}
            </div>
          )}
          {drafts.data && drafts.data.length > 1 && (
            <>
              <h3 className="mt-5 text-[14px] font-semibold">Other drafts</h3>
              <ul className="mt-1">
                {drafts.data
                  .filter((d) => d.group_id !== current?.group_id)
                  .slice(0, 4)
                  .map((d) => (
                    <li key={d.group_id}>
                      <button className="flex w-full justify-between gap-3 py-1.5 text-left text-[13.5px] hover:underline" onClick={() => { setCurrent(d); setVersion(d.version); setAnchor(""); }}>
                        <span className="truncate">{d.business_name}</span>
                        <span className="shrink-0 text-[#5B616B]">{timeAgo(d.created_at)}</span>
                      </button>
                    </li>
                  ))}
              </ul>
            </>
          )}
        </Card>
      </Section>

      {current && previewSrc && (
        <Section shot="sites" wide>
          <Card className="!p-0 overflow-hidden">
            <iframe key={previewSrc} title="Website draft preview" src={`${previewSrc}${anchor}`} sandbox="" className="h-[64vh] w-full bg-white" />
            <div className="flex flex-wrap items-center gap-2 border-t border-black/[0.07] px-5 py-3 text-[12.5px] text-[#5B616B]">
              <Pill>{current.generated_by === "ai" ? "Written by Claude" : "Offline template"}</Pill>
              <span className="truncate">Stored at {current.html_url}</span>
            </div>
          </Card>
        </Section>
      )}
    </>
  );
}
