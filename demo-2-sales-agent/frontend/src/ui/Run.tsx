import { useEffect, useRef, useState, type FormEvent } from "react";
import { AnimatePresence, motion } from "motion/react";
import { api, num, SIGNAL_LABELS, TOOL_LABELS, type Icp, type RunEvent } from "../api";
import { refresh } from "../data";
import { startRun } from "../actions";
import { useAgent } from "../store";
import { clock, day } from "../lib/format";
import { cn } from "../lib/cn";
import { Button, ErrorNote, Field, Input, Note, Panel, Part, Section, StatusBadge, TextArea, useAction } from "./kit";

const KIND_LABEL: Record<RunEvent["kind"], string> = { tool: "", note: "Note", error: "Refused", done: "Finished" };
const label = (e: RunEvent) => (e.kind === "tool" && e.tool ? TOOL_LABELS[e.tool] ?? e.tool : KIND_LABEL[e.kind]);
const list = (v: string) => v.split(",").map((s) => s.trim()).filter(Boolean);
const ms = (v: number | null) => (v == null ? "" : v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1)} s`);

function LiveLog() {
  const live = useAgent((s) => s.live);
  const end = useRef<HTMLLIElement>(null);
  const count = live?.events.length ?? 0;
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [count]);
  if (!live) return <p className="empty">Press Run the agent and each step appears here as it happens: what it searched, which leads it saved, which emails it drafted.</p>;
  return (
    <ol className="runlog" role="log" aria-live="polite" aria-label={`Run ${live.runId}, step by step`}>
      <AnimatePresence initial={false}>
        {live.events.filter((e) => e.kind !== "done" && e.tool !== "finish").map((e) => (
          <motion.li key={e.seq} className={cn(`is-${e.kind}`)} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
            <span className="tool">{label(e)}</span>
            <span>{e.summary}{e.ms != null && e.kind === "tool" && <span className="ms">{ms(e.ms)}</span>}</span>
          </motion.li>
        ))}
      </AnimatePresence>
      <li ref={end} aria-hidden="true" style={{ border: 0, padding: 0 }} />
    </ol>
  );
}

function History() {
  const runs = useAgent((s) => s.runs);
  if (!runs.length) return null;
  const tokens = runs.some((r) => r.input_tokens + r.output_tokens > 0);
  return (
    <Part title="Every run is logged" foot={tokens ? "Tokens are the counts Claude's API reported for that run." : "Token counts appear once the agent runs on Claude."}>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th scope="col">Started</th><th scope="col">Result</th><th scope="col" className="num">Tool calls</th><th scope="col" className="num">Leads</th><th scope="col" className="num">Drafts</th>{tokens && <th scope="col" className="num">Tokens</th>}</tr>
          </thead>
          <tbody>
            {runs.slice(0, 6).map((r) => (
              <tr key={r.id}>
                <td>{day(r.started_at)}, {clock(r.started_at)}<span className="why">{r.engine.startsWith("live") ? "Claude" : "Offline agent"}</span></td>
                <td><StatusBadge status={r.status} /></td>
                <td className="num">{r.tools_called.length}</td>
                <td className="num">{r.tool_counts.save_lead ?? 0}</td>
                <td className="num">{(r.tool_counts.create_draft ?? 0) + (r.tool_counts.recommend_followup ?? 0)}</td>
                {tokens && <td className="num">{num(r.input_tokens + r.output_tokens)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Part>
  );
}

/** The ideal customer profile the agent works from. A rep's edit wins over the agent's version. */
function Profile() {
  const [icp, setIcp] = useState<Icp | null>(null);
  const [form, setForm] = useState({ summary: "", industries: "", size_min: "", size_max: "", regions: "", exclusions: "", signals: [] as string[] });
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();
  const runs = useAgent((s) => s.runs.length);

  useEffect(() => {
    void api.icp().then(({ icp: current, default: fallback }) => {
      const p = current ?? fallback;
      setIcp(current);
      setForm({ summary: p.summary, industries: p.industries.join(", "), size_min: String(p.size_min), size_max: String(p.size_max),
        regions: p.regions.join(", "), exclusions: p.exclusions.join(", "), signals: p.signals });
    }).catch(() => undefined);
  }, [runs]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    void run("save", async () => {
      const r = await api.saveIcp({ summary: form.summary, industries: list(form.industries), size_min: Number(form.size_min), size_max: Number(form.size_max),
        regions: list(form.regions), exclusions: list(form.exclusions), signals: form.signals });
      setIcp(r.icp);
      setSaved(true);
    });
  };
  const toggle = (key: string) => setForm((f) => ({ ...f, signals: f.signals.includes(key) ? f.signals.filter((s) => s !== key) : [...f.signals, key] }));
  const who = !icp ? "Not saved yet. The agent writes it from Acme's notes on its first run." : icp.edited_by === "rep"
    ? `Edited by you on ${day(icp.updated_at)}. The agent keeps your version.` : `Written by the agent on ${day(icp.updated_at)}.`;

  return (
    <Part title="Who the agent looks for" foot={who}>
      <p className="small">{icp?.summary ?? form.summary}</p>
      <details className="profile">
        <summary>Edit the profile</summary>
        <form className="form" onSubmit={submit}>
          <Field label="In one or two sentences"><TextArea rows={3} value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} required minLength={10} maxLength={600} /></Field>
          <div className="form-row">
            <Field label="Smallest company (staff)"><Input type="number" min={1} value={form.size_min} onChange={(e) => setForm({ ...form, size_min: e.target.value })} required /></Field>
            <Field label="Largest company (staff)"><Input type="number" min={1} value={form.size_max} onChange={(e) => setForm({ ...form, size_max: e.target.value })} required /></Field>
          </div>
          <Field label="Industries" hint="Separate with commas."><Input value={form.industries} onChange={(e) => setForm({ ...form, industries: e.target.value })} /></Field>
          <Field label="Regions" hint="Separate with commas."><Input value={form.regions} onChange={(e) => setForm({ ...form, regions: e.target.value })} /></Field>
          <Field label="Never contact" hint="Separate with commas."><Input value={form.exclusions} onChange={(e) => setForm({ ...form, exclusions: e.target.value })} /></Field>
          <fieldset className="field">
            <legend className="field-label">Buying signals that count</legend>
            <div className="chips mt-1">
              {Object.entries(SIGNAL_LABELS).map(([key, text]) => (
                <label key={key} className={cn("chip", form.signals.includes(key) && "is-on")}>
                  <input type="checkbox" className="sr-only" checked={form.signals.includes(key)} onChange={() => toggle(key)} />
                  {text}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="actions" style={{ marginTop: 0 }}>
            <Button type="submit" variant="secondary" busy={busy === "save"}>Save profile</Button>
          </div>
          <ErrorNote error={error} />
          {saved && <Note>Profile saved. The next run scores leads against it.</Note>}
        </form>
      </details>
    </Part>
  );
}

export function Run() {
  const status = useAgent((s) => s.status);
  const live = useAgent((s) => s.live);
  const runs = useAgent((s) => s.runs);
  const [error, setError] = useState<string | null>(null);
  const running = !!live && !live.done;
  const found = live?.done ? runs.find((r) => r.id === live.runId) : undefined;
  const last = found && found.status !== "running" ? found : null;

  const intro = !status ? "Connecting to the agent." : status.live_model
    ? `Claude (${status.engine.replace(/^live Claude \(|\)$/g, "")}) runs the loop and picks each tool itself. ${status.live_search ? "Searches go to Tavily live." : "Searches use real web results saved on " + day(status.snapshot_date) + "."}`
    : `No Claude key is set, so an offline agent drives the same nine tools with the same checks, using real web results saved on ${day(status.snapshot_date)}. It pauses briefly between steps so you can follow along.`;

  return (
    <Section id="run" scene={1}>
      <Panel id="run" title="Watch it work" intro={intro} busy={running}>
        <div className="actions">
          <Button busy={running} onClick={() => { setError(null); void startRun().then(setError); }}>
            {running ? "Running" : "Run the agent"}
          </Button>
          <span className="small">Every tool call lights up its token on the desk.</span>
        </div>
        <ErrorNote error={error} />
        <LiveLog />
        {last && (
          <p className={cn("note", last.status === "failed" && "note-bad")} role="status">
            {last.status === "failed" ? `The run failed: ${last.error ?? "unknown error"}. It's in the log, and Slack is alerted when connected.` : last.outcome}
          </p>
        )}
        {live?.done && <div className="actions"><a className="link" href="#leads" onClick={() => void refresh("leads")}>See the leads it found</a></div>}
        <Profile />
        <History />
      </Panel>
    </Section>
  );
}
