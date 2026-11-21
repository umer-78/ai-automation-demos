import { useMemo, useState, type FormEvent } from "react";
import { api, SERVICES, type Client, type OnboardingResult, type Service, type Step } from "../api";
import { hub, useHub } from "../store";
import { refresh } from "../data";
import { RevealList } from "../components/RevealList";
import { notSent, slackText } from "../lib/format";
import { cn } from "../lib/cn";
import { Button, ErrorNote, Field, Input, Note, Panel, Part, Section, Segmented, Select, StatusBadge, useAction } from "./kit";

const STEP_STATION: [RegExp, number][] = [
  [/^Airtable/, 0], [/^Make/, 1], [/^Create task/, 2], [/^Post Slack/, 4], [/^Claude/, 2], [/^Save brief/, 3], [/^Email/, 2],
];

/** The 3D stations to light, in order, for the steps that really ran. */
export function stationsFor(steps: Step[]) {
  const out: number[] = [];
  for (const s of steps) {
    if (s.status !== "ok" && s.status !== "saved") continue;
    const hit = STEP_STATION.find(([re]) => re.test(s.name));
    if (hit && out[out.length - 1] !== hit[1]) out.push(hit[1]);
  }
  return out;
}

interface Outcome { id: number; runs: OnboardingResult[]; viaMake: boolean }
const BLANK = { name: "", website: "", industry: "", manager: "", manager_email: "" };
const optional = (v: string) => v.trim() || undefined;

function OutcomeView({ outcome }: { outcome: Outcome }) {
  const [shown, setShown] = useState(0);
  const run = outcome.runs[shown];
  if (!run) return null;
  return (
    <div aria-live="polite">
      <Part title={`${run.client} is set up for ${run.service}`}
        foot={`${outcome.viaMake ? "Ran through Airtable and Make" : "Ran directly in the hub"} in ${run.elapsed_s < 1 ? `${Math.max(1, Math.round(run.elapsed_s * 1000))} ms` : `${run.elapsed_s.toFixed(1)} seconds`}.`}>
        {outcome.runs.length > 1 && (
          <div className="chips mt-3">
            {outcome.runs.map((r, i) => (
              <button key={r.service} type="button" className={cn("chip", i === shown && "is-on")} aria-pressed={i === shown} onClick={() => setShown(i)}>
                {r.service}
              </button>
            ))}
          </div>
        )}
        <RevealList key={shown} className="steps" delay={450}>
          {run.steps.map((s, i) => (
            <div key={s.name} className="step">
              <span className="step-n" aria-hidden="true">{i + 1}</span>
              <div className="min-w-0">
                <p className="step-name">{s.name} <StatusBadge status={s.status} /></p>
                <p className="small">{s.detail}</p>
              </div>
            </div>
          ))}
        </RevealList>
      </Part>
      <Part title="Slack welcome" foot={run.slack.sent ? "Posted to Slack." : `Not posted. ${notSent("Slack", run.slack.detail)}`}>
        <div className="slack">
          <span className="slack-avatar" aria-hidden="true">N</span>
          <div className="min-w-0">
            <p className="slack-name">Northwind Hub</p>
            <p className="whitespace-pre-line">{slackText(run.slack.text)}</p>
          </div>
        </div>
      </Part>
      <Part title="Client brief" foot={`Written by ${run.engine}.`}>
        <dl className="facts facts-stacked">
          <div><dt>Audience</dt><dd>{run.brief.audience}</dd></div>
          <div><dt>Tone</dt><dd>{run.brief.tone}</dd></div>
          <div><dt>Quick wins</dt><dd><ul className="bullets">{run.brief.quick_wins.map((w) => <li key={w}>{w}</li>)}</ul></dd></div>
        </dl>
      </Part>
      <Part title="Email to the account manager" foot={run.email.sent ? "Sent." : `Saved as a draft. ${notSent("Email sending", run.email.detail)}`}>
        <p className="small mt-1">To {run.email.to ?? "no address on file"}</p>
        <p className="mt-1 font-semibold">{run.email.subject}</p>
        <p className="mail-body">{run.email.body}</p>
      </Part>
    </div>
  );
}

function Offboard({ clients }: { clients: Client[] }) {
  const [id, setId] = useState("");
  const [armed, setArmed] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const act = useAction();
  const target = clients.find((c) => c.id === id) ?? clients[0];

  const run = async () => {
    if (!target) return;
    const r = await act.run("churn", () => api.churn(target.id));
    setArmed(false);
    if (!r) return;
    setDone(`${r.client} is archived and ${r.tasks_closed} open ${r.tasks_closed === 1 ? "task was" : "tasks were"} closed. ${
      r.slack.sent ? "The team was told in Slack." : "Slack isn't set up, so nothing was posted."}`);
    hub.sendPackets(r.slack.sent ? [2, 3, 4] : [2, 3]);
    void refresh("clients", "log", "status", "dashboard");
  };

  return (
    <Part title="Off-board a client" foot="Closes their open tasks, archives them here and in Airtable, and posts a summary to Slack.">
      {clients.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Select aria-label="Client to off-board" className="min-w-0 flex-1" value={target?.id ?? ""} onChange={(e) => { setId(e.target.value); setArmed(false); }}>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
          {armed ? (
            <>
              <Button variant="danger" busy={act.busy === "churn"} onClick={run}>Off-board {target?.name}</Button>
              <Button variant="quiet" onClick={() => setArmed(false)}>Cancel</Button>
            </>
          ) : (
            <Button variant="secondary" onClick={() => { setArmed(true); setDone(null); }}>Off-board</Button>
          )}
        </div>
      ) : (
        <p className="small mt-2">No active clients to off-board.</p>
      )}
      <ErrorNote error={act.error} />
      {done && <Note>{done}</Note>}
    </Part>
  );
}

export function Onboarding() {
  const clients = useHub((s) => s.clients);
  const active = useMemo(() => clients.filter((c) => c.status !== "Archived"), [clients]);
  const [tab, setTab] = useState<"new" | "existing">("new");
  const [form, setForm] = useState(BLANK);
  const [services, setServices] = useState<Service[]>(["SEO"]);
  const [pick, setPick] = useState("");
  const [service, setService] = useState<Service>("Paid Ads");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const act = useAction();

  const finish = (runs: OnboardingResult[], viaMake: boolean) => {
    setOutcome({ id: Date.now(), runs, viaMake });
    hub.sendPackets(stationsFor(runs[0]?.steps ?? []));
    void refresh("clients", "log", "status");
  };
  const bind = (k: keyof typeof BLANK) => ({
    value: form[k],
    onChange: (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value })),
  });
  const toggle = (s: Service) => setServices((xs) => (xs.includes(s) ? xs.filter((x) => x !== s) : [...xs, s]));

  const addClient = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return act.setError("Enter the client's business name.");
    if (!services.length) return act.setError("Pick at least one service.");
    const r = await act.run("add", () =>
      api.addClient({
        name: form.name.trim(), website: optional(form.website), industry: optional(form.industry), services,
        manager: optional(form.manager), manager_email: optional(form.manager_email),
      }),
    );
    if (!r) return;
    finish(r.onboarding, r.mode === "airtable+make");
    setForm(BLANK);
  };

  const onboard = async (e: FormEvent) => {
    e.preventDefault();
    const id = pick || active[0]?.id;
    if (!id) return act.setError("There are no active clients yet. Add one first.");
    const r = await act.run("onboard", () => api.onboard(id, service));
    if (r) finish([r], false);
  };

  return (
    <Section id="onboarding" scene={1}>
      <Panel id="onboarding" busy={act.busy !== null} title="Onboard a client"
        intro="New clients start as a row in Airtable. Make hands the row to the hub, which creates the task list, posts a Slack welcome, asks Claude for a client brief and drafts an email to the account manager.">
        <Segmented label="Client type" value={tab} onChange={(v) => { setTab(v); act.setError(null); }}
          options={[["new", "New client"], ["existing", "Existing client"]]} />
        {tab === "new" ? (
          <form className="form" onSubmit={addClient} noValidate>
            <Field label="Business name"><Input {...bind("name")} placeholder="Harbour Physio" required autoComplete="organization" /></Field>
            <div className="form-row">
              <Field label="Website"><Input {...bind("website")} placeholder="harbourphysio.com" inputMode="url" /></Field>
              <Field label="Industry"><Input {...bind("industry")} placeholder="Physiotherapy" /></Field>
            </div>
            <fieldset className="field">
              <legend className="field-label">Services</legend>
              <div className="chips">
                {SERVICES.map((s) => (
                  <label key={s} className={cn("chip", services.includes(s) && "is-on")}>
                    <input type="checkbox" className="sr-only" checked={services.includes(s)} onChange={() => toggle(s)} />
                    {s}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="form-row">
              <Field label="Account manager"><Input {...bind("manager")} placeholder="Sara Lind" autoComplete="name" /></Field>
              <Field label="Manager's email"><Input {...bind("manager_email")} type="email" placeholder="sara@northwind.example" autoComplete="email" /></Field>
            </div>
            <Button type="submit" busy={act.busy === "add"}>{act.busy === "add" ? "Adding client" : "Add client"}</Button>
          </form>
        ) : (
          <form className="form" onSubmit={onboard}>
            <div className="form-row">
              <Field label="Client">
                <Select value={pick || active[0]?.id || ""} onChange={(e) => setPick(e.target.value)}>
                  {active.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </Select>
              </Field>
              <Field label="Service">
                <Select value={service} onChange={(e) => setService(e.target.value as Service)}>
                  {SERVICES.map((s) => <option key={s}>{s}</option>)}
                </Select>
              </Field>
            </div>
            <Button type="submit" busy={act.busy === "onboard"}>{act.busy === "onboard" ? "Running onboarding" : "Run onboarding"}</Button>
          </form>
        )}
        <ErrorNote error={act.error} />
        {outcome && <OutcomeView key={outcome.id} outcome={outcome} />}
        <Offboard clients={active} />
      </Panel>
    </Section>
  );
}
