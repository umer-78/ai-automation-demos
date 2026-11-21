import clsx from "clsx";
import { motion } from "motion/react";
import { Check, CircleAlert, Loader2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api, type RunStatus } from "../lib/api";
import { stepName } from "../lib/format";
import { dataChanged } from "../lib/hooks";
import { Button, Drawer, ErrorNote, Field, useToast } from "./ui";

const SERVICES = ["SEO", "Paid Ads", "Web Design"] as const;
const EMPTY = { name: "", website: "", industry: "", manager: "", manager_email: "", services: ["SEO"] as string[] };

export default function OnboardingDrawer({ open, onClose, onStarted, onFinished }: {
  open: boolean;
  onClose: () => void;
  onStarted?: () => void;
  onFinished?: (ok: boolean, services: string[]) => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [mode, setMode] = useState<string>("local");
  const [run, setRun] = useState<RunStatus | null>(null);

  useEffect(() => {
    if (!open) {
      setRunId(null);
      setRun(null);
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    if (!runId) return;
    let stop = false;
    const tick = async () => {
      try {
        const r = await api.get<RunStatus>(`/api/automation/runs/${runId}`);
        if (stop) return;
        setRun(r);
        if (r.status === "running") window.setTimeout(tick, 700);
        else {
          dataChanged();
          onFinished?.(r.status === "success", form.services);
          if (r.status === "success") toast("success", `${form.name} is onboarded. Brief emailed to ${form.manager} as a draft.`);
          else toast("failure", "Onboarding failed. It is in the automation log and Slack was alerted.");
        }
      } catch {
        if (!stop) window.setTimeout(tick, 1200);
      }
    };
    void tick();
    return () => void (stop = true);
  }, [runId]);

  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const toggle = (s: string) =>
    setForm((f) => ({ ...f, services: f.services.includes(s) ? f.services.filter((x) => x !== s) : [...f.services, s] }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.services.length) return setError("Pick at least one service.");
    setBusy(true);
    try {
      const res = await api.post<{ run_id: string; mode: string }>("/api/clients", {
        ...form,
        website: form.website || null,
        manager_email: form.manager_email || null,
      });
      setMode(res.mode);
      setRunId(res.run_id);
      onStarted?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const steps = run?.log[0]?.details?.steps ?? run?.live?.steps ?? [];
  const finished = run && run.status !== "running";

  return (
    <Drawer open={open} onClose={onClose} title={runId ? "Onboarding in progress" : "Add a client"}>
      {!runId ? (
        <form onSubmit={submit} className="space-y-4">
          <p className="text-[14px] text-slate">
            This does what an Airtable row does: the router picks a checklist per service, posts a Slack welcome, writes the brief and emails it to the account manager.
          </p>
          <Field label="Client name">
            <input required minLength={2} maxLength={120} className="field" value={form.name} onChange={set("name")} placeholder="Coastal Coffee Roasters" />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Website" hint="Fake domains like .example are fine">
              <input className="field" value={form.website} onChange={set("website")} placeholder="coastalcoffee.example" />
            </Field>
            <Field label="Industry">
              <input required minLength={2} className="field" value={form.industry} onChange={set("industry")} placeholder="Food & beverage" />
            </Field>
          </div>
          <fieldset>
            <legend className="mb-1.5 text-[13.5px] font-medium">Services</legend>
            <div className="flex flex-wrap gap-2">
              {SERVICES.map((s) => (
                <button
                  type="button"
                  key={s}
                  aria-pressed={form.services.includes(s)}
                  onClick={() => toggle(s)}
                  className={clsx(
                    "rounded-lg border px-3 py-1.5 text-[14px] transition-colors",
                    form.services.includes(s) ? "border-aurora/60 bg-aurora/15 text-ink" : "border-edge bg-surface text-slate hover:text-ink",
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
          </fieldset>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Account manager">
              <input required minLength={2} className="field" value={form.manager} onChange={set("manager")} placeholder="Elena Rossi" />
            </Field>
            <Field label="Manager email" hint="Receives the brief draft">
              <input type="email" className="field" value={form.manager_email} onChange={set("manager_email")} placeholder="elena@northwind-digital.example" />
            </Field>
          </div>
          {error && <ErrorNote message={error} />}
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" busy={busy}>Start onboarding</Button>
          </div>
        </form>
      ) : (
        <div>
          <p className="mb-5 text-[14px] text-slate">
            {mode === "make" ? "Sent to the Make.com scenario. Steps appear as Make calls the hub." : "Running the same steps as the Make scenario."} Run <code className="text-ink">{runId}</code>
          </p>
          <ol className="space-y-3">
            {steps.map((s, i) => (
              <motion.li key={i} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} className="flex items-start gap-3">
                <span className="mt-0.5 grid size-5 place-items-center rounded-full bg-aurora-soft text-aurora-ink"><Check className="size-3.5" /></span>
                <div>
                  <div className="font-medium">{stepName[s.step] ?? s.step}{s.service ? `: ${String(s.service)}` : ""}</div>
                  <div className="num text-[12.5px] text-slate">{(s.at_ms / 1000).toFixed(2)} s</div>
                </div>
              </motion.li>
            ))}
            {!finished && (
              <li className="flex items-center gap-3 text-slate">
                <Loader2 className="size-5 animate-spin" /> Working
              </li>
            )}
          </ol>
          {finished && run?.status === "failure" && (
            <div className="mt-5 flex items-start gap-2 rounded-lg border border-ember/30 bg-ember-soft px-4 py-3 text-[14px] text-ember-ink">
              <CircleAlert className="mt-0.5 size-4 shrink-0" />
              {run.log[0]?.error ?? run.live?.error}
            </div>
          )}
          {finished && run?.status === "success" && (
            <div className="mt-5 rounded-lg border border-aurora/40 bg-aurora-soft px-4 py-3 text-[14px] text-aurora-ink">
              Done in {((run.log[0]?.duration_ms ?? 0) / 1000).toFixed(2)} s. The client is now active and appears in reporting after the next daily run.
            </div>
          )}
          <div className="mt-6 flex justify-end gap-2">
            {finished && <Button onClick={() => { setRunId(null); setRun(null); setForm(EMPTY); }}>Add another</Button>}
            <Button variant="primary" onClick={onClose}>Close</Button>
          </div>
        </div>
      )}
    </Drawer>
  );
}
