import { PageIntro, Section } from "../world/Section";
import clsx from "clsx";
import { Fragment, useCallback, useEffect, useState, type ReactNode } from "react";
import { Button, Chip, ErrorNote, Panel, Skeleton, Tabs, useToast } from "../components/ui";
import { api, type IcpChange, type IcpCriteria, type IcpPayload, type KnowledgeDoc } from "../lib/api";
import { shortDate } from "../lib/format";
import { dataChanged, useApi, useOnDataChanged } from "../lib/hooks";

type Bucket = "target" | "adjacent" | "neutral" | "excluded";
const BUCKETS: { value: Bucket; label: string }[] = [
  { value: "target", label: "Target" },
  { value: "adjacent", label: "Adjacent" },
  { value: "neutral", label: "Neutral" },
  { value: "excluded", label: "Skip" },
];

function bucketOf(c: IcpCriteria, cat: string): Bucket {
  if (c.target_categories.includes(cat)) return "target";
  if (c.adjacent_categories.includes(cat)) return "adjacent";
  if (c.excluded_categories.includes(cat)) return "excluded";
  return "neutral";
}

function setBucket(c: IcpCriteria, cat: string, b: Bucket): IcpCriteria {
  const strip = (list: string[]) => list.filter((x) => x !== cat);
  const next = { ...c, target_categories: strip(c.target_categories), adjacent_categories: strip(c.adjacent_categories), excluded_categories: strip(c.excluded_categories) };
  if (b === "target") next.target_categories.push(cat);
  if (b === "adjacent") next.adjacent_categories.push(cat);
  if (b === "excluded") next.excluded_categories.push(cat);
  return next;
}

/** Just enough Markdown for the notes: headings, bullets, bold and table rows. */
function inline(text: string): ReactNode {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => (part.startsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>));
}
function Notes({ text }: { text: string }) {
  return (
    <div className="space-y-1.5 text-[14.5px] leading-relaxed">
      {text.split("\n").map((line, i) => {
        if (line.startsWith("# ")) return <h3 key={i} className="heading pt-3 text-[18px]">{line.slice(2)}</h3>;
        if (line.startsWith("## ")) return <h4 key={i} className="heading pt-2 text-[15.5px]">{line.slice(3)}</h4>;
        if (/^\s*-\s/.test(line))
          return (
            <p key={i} className="relative pl-4">
              <span className="absolute left-1 top-[0.68em] size-1.5 rounded-full bg-ink-3" aria-hidden />
              {inline(line.trim().slice(2))}
            </p>
          );
        if (/^\s*\d+\.\s/.test(line)) return <p key={i} className="pl-4">{inline(line.trim())}</p>;
        if (line.startsWith("|")) {
          if (/^\|\s*-/.test(line)) return null;
          return <p key={i} className="grid grid-cols-3 gap-2 border-b border-rule-soft py-1 text-[13.5px]">{line.split("|").slice(1, -1).map((cell, j) => <span key={j}>{inline(cell.trim())}</span>)}</p>;
        }
        return line.trim() ? <p key={i}>{inline(line)}</p> : null;
      })}
    </div>
  );
}

export default function Profile() {
  const { data, error, reload } = useApi<IcpPayload>("/api/icp");
  const { data: docs } = useApi<KnowledgeDoc[]>("/api/knowledge");
  useOnDataChanged(useCallback(() => void reload(), [reload]));
  const toast = useToast();
  const [draft, setDraft] = useState<IcpCriteria | null>(null);
  const [exclusions, setExclusions] = useState("");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<IcpChange[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [doc, setDoc] = useState("product");

  useEffect(() => {
    if (data) {
      setDraft(data.active.criteria);
      setExclusions(data.active.criteria.exclusions.join("\n"));
      setPreview(null);
    }
  }, [data]);

  if (error || !data || !draft)
    return (
      <Section shot="profile" wide="xl">
        {error ? <ErrorNote message={error} /> : <Skeleton className="h-[600px] w-full rounded-[22px]" />}
      </Section>
    );
  const opts = data.options;
  const payload = () => ({ ...draft, exclusions: exclusions.split("\n").map((s) => s.trim()).filter(Boolean), note: note || undefined });
  const update = (patch: Partial<IcpCriteria>) => {
    setDraft({ ...draft, ...patch });
    setPreview(null);
  };

  const doPreview = async () => {
    setBusy("preview");
    try {
      const res = await api.post<{ changes: IcpChange[] }>("/api/icp/preview", payload());
      setPreview(res.changes);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };
  const save = async () => {
    setBusy("save");
    try {
      const res = await api.put<{ saved: { version: number } }>("/api/icp", payload());
      toast("success", `Saved as version ${res.saved.version}. Leads and accounts were re-scored.`);
      setNote("");
      dataChanged();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const active = data.active;
  const moved = (preview ?? []).filter((c) => c.delta !== 0 || c.old_status !== c.new_status);

  return (
    <Section shot="profile" wide="xl">
      <div className="space-y-4">
      <PageIntro
        title="Ideal customer profile"
        description="The agent writes the first version from the product notes, competitor notes and deal history. Edit anything; your version always wins, and every lead and account is re-scored against it."
      />
      <div className="flex flex-wrap items-center gap-2 text-[14px] text-ink-2">
        <Chip tone={active.author === "rep" ? "cobalt" : active.author === "agent" ? "amber" : "neutral"}>
          {active.author === "default" ? "Default profile, the agent writes v1 on its first run" : `Version ${active.version}, by ${active.author === "rep" ? "the rep" : "the agent"}`}
        </Chip>
        {active.created_at && <span>{shortDate(active.created_at)}</span>}
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
        <div className="space-y-6">
          <Panel title="Summary">
            <textarea className="field min-h-[110px]" value={draft.summary} onChange={(e) => update({ summary: e.target.value })} aria-label="Profile summary" />
          </Panel>
          <Panel title="Company type" subtitle="Target gets full fit points, adjacent half, skipped companies are excluded">
            <div className="divide-y divide-rule-soft">
              {Object.entries(opts.categories).map(([key, label]) => (
                <div key={key} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="text-[14.5px]">{label}</span>
                  <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-rule bg-sheet p-0.5">
                    {BUCKETS.map((b) => {
                      const on = bucketOf(draft, key) === b.value;
                      return (
                        <button
                          key={b.value}
                          role="radio"
                          aria-checked={on}
                          onClick={() => update(setBucket(draft, key, b.value))}
                          className={clsx(
                            "rounded-md px-2.5 py-1 text-[12.5px] font-semibold transition-colors",
                            on ? (b.value === "excluded" ? "bg-crimson text-sheet" : b.value === "target" ? "bg-spruce text-sheet" : "bg-sage-soft text-ink") : "text-ink-3 hover:text-ink",
                          )}
                        >
                          {b.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          <div className="grid gap-6 md:grid-cols-2">
            <Panel title="Company size">
              <div className="flex flex-wrap items-center gap-2 text-[14px]">
                <input type="number" min={1} className="field !w-28" value={draft.employee_min} onChange={(e) => update({ employee_min: Number(e.target.value) })} aria-label="Minimum employees" />
                <span>to</span>
                <input type="number" min={1} className="field !w-28" value={draft.employee_max} onChange={(e) => update({ employee_max: Number(e.target.value) })} aria-label="Maximum employees" />
                <span>employees</span>
              </div>
            </Panel>
            <Panel title="Regions">
              <div className="flex flex-wrap gap-2">
                {opts.regions.map((r) => {
                  const on = draft.regions.includes(r);
                  return (
                    <button
                      key={r}
                      aria-pressed={on}
                      onClick={() => update({ regions: on ? draft.regions.filter((x) => x !== r) : [...draft.regions, r] })}
                      className={clsx("rounded-full border px-3 py-1 text-[13px] font-semibold transition-colors", on ? "border-spruce bg-spruce text-sheet" : "border-rule bg-sheet text-ink-2 hover:border-ink-3/50")}
                    >
                      {r}
                    </button>
                  );
                })}
              </div>
            </Panel>
          </div>
          <Panel title="Buying signals" subtitle="Points each signal adds, up to 30">
            <div className="space-y-3">
              {Object.entries(opts.signals).map(([key, label]) => (
                <label key={key} className="grid grid-cols-[1fr_160px_36px] items-center gap-3 text-[14.5px]">
                  <span className="first-letter:uppercase">{label}</span>
                  <input type="range" min={0} max={30} value={draft.signal_weights[key] ?? 0} onChange={(e) => update({ signal_weights: { ...draft.signal_weights, [key]: Number(e.target.value) } })} className="accent-amber" />
                  <span className="num text-right font-bold">{draft.signal_weights[key] ?? 0}</span>
                </label>
              ))}
            </div>
          </Panel>
          <Panel title="Exclusions in plain words" subtitle="One per line. The agent reads these in its prompt.">
            <textarea className="field min-h-[110px]" value={exclusions} onChange={(e) => setExclusions(e.target.value)} aria-label="Exclusions" />
          </Panel>
          <div className="panel flex flex-wrap items-end gap-3 p-5">
            <label className="min-w-[240px] flex-1 text-[14px] font-semibold">
              Note for this version (optional)
              <input className="field mt-1" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} placeholder="For example: no fintech this quarter" />
            </label>
            <Button busy={busy === "preview"} onClick={() => void doPreview()}>
              Preview the impact
            </Button>
            <Button variant="dark" busy={busy === "save"} onClick={() => void save()}>
              Save as version {active.version + 1}
            </Button>
          </div>
        </div>

        <div className="space-y-6">
          {preview && (
            <Panel title="What would change" subtitle={moved.length ? `${moved.length} of ${preview.length} leads change` : "No lead changes"} padded={false}>
              <ul className="max-h-[420px] divide-y divide-rule-soft overflow-y-auto">
                {preview.map((c) => (
                  <li key={c.lead_id} className="flex items-center gap-3 px-5 py-2 text-[14px]">
                    <span className="min-w-0 flex-1 truncate font-semibold">{c.company}</span>
                    <span className="num text-ink-3">{c.old_score}</span>
                    <span className="num w-10 text-right font-bold">{c.new_score}</span>
                    <span className={clsx("num w-12 text-right text-[13px] font-semibold", c.delta > 0 ? "text-moss" : c.delta < 0 ? "text-crimson" : "text-ink-3")}>
                      {c.delta > 0 ? `+${c.delta}` : c.delta}
                    </span>
                    {c.old_status !== c.new_status && <Chip tone={c.new_status === "excluded" ? "crimson" : "moss"}>{c.new_status}</Chip>}
                  </li>
                ))}
                {preview.length === 0 && <li className="px-5 py-6 text-[14px] text-ink-3">No leads yet. Run the agent first.</li>}
              </ul>
            </Panel>
          )}
          <Panel title="Version history" padded={false}>
            <ul className="divide-y divide-rule-soft">
              {data.history.map((v) => (
                <li key={v.version} className="px-5 py-3 text-[14px]">
                  <div className="flex items-center gap-2">
                    <span className="font-bold">v{v.version}</span>
                    <Chip tone={v.author === "rep" ? "cobalt" : "amber"}>{v.author === "rep" ? "Rep" : "Agent"}</Chip>
                    <span className="text-[12.5px] text-ink-3">{shortDate(v.created_at)}</span>
                  </div>
                  {v.note && <p className="mt-0.5 text-ink-2">{v.note}</p>}
                </li>
              ))}
              {data.history.length === 0 && <li className="px-5 py-5 text-[14px] text-ink-3">The agent writes version 1 on its first run.</li>}
            </ul>
          </Panel>
          <Panel title="What the agent reads first" padded={false}>
            <div className="px-5 pt-2">
              <Tabs label="Notes" value={doc} onChange={setDoc} options={(docs ?? []).map((d) => ({ value: d.name, label: d.title }))} />
            </div>
            <div className="max-h-[560px] overflow-y-auto px-5 pb-5 pt-2">{docs ? <Notes text={docs.find((d) => d.name === doc)?.content ?? ""} /> : <Skeleton className="h-60" />}</div>
          </Panel>
        </div>
      </div>
      </div>
    </Section>
  );
}
