import { Card, CardTitle, Section, btn } from "../world/Section";
import { sendRun, world } from "../world/store";
import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { Fragment, useCallback, useState } from "react";
import { Empty, ErrorNote, Pill, Segmented, Skeleton, statusTone, useToast } from "../components/ui";
import { api, type AutomationStats, type LogRow, type Notification, type Status } from "../lib/api";
import { slackText, stepName, timeAgo, workflowName } from "../lib/format";
import { dataChanged, useApi, useOnDataChanged, useStatus } from "../lib/hooks";

const integrationLabel: Record<string, string> = {
  ai: "AI model",
  database: "Database",
  slack: "Slack",
  email: "Email",
  airtable: "Airtable",
  make: "Make.com",
  storage: "File storage",
};

function LogTable({ rows }: { rows: LogRow[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-[14px]">
        <thead className="table-head">
          <tr><th>Workflow</th><th>Source</th><th>Status</th><th className="text-right">Duration</th><th>When</th><th className="w-10" /></tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const steps = r.details?.steps ?? [];
            const expanded = open === r.id;
            return (
              <Fragment key={r.id}>
                <tr className={clsx("table-row", r.status === "failure" && "bg-ember-soft/40")}>
                  <td>
                    <div className="font-medium">{workflowName[r.workflow] ?? r.workflow}</div>
                    {r.error && <div className="max-w-[520px] truncate text-[12.5px] text-ember-ink" title={r.error}>{r.error}</div>}
                  </td>
                  <td className="text-slate">{r.source}</td>
                  <td><Pill tone={statusTone(r.status)}>{r.status}</Pill></td>
                  <td className="num text-right">{r.duration_ms != null ? `${r.duration_ms} ms` : "n/a"}</td>
                  <td className="text-slate">{timeAgo(r.created_at)}</td>
                  <td>
                    <button aria-expanded={expanded} aria-label="Show details" onClick={() => setOpen(expanded ? null : r.id)} className="rounded p-1 text-slate hover:bg-ink/[0.06]">
                      <ChevronDown className={clsx("size-4 transition-transform", expanded && "rotate-180")} />
                    </button>
                  </td>
                </tr>
                {expanded && (
                  <tr>
                    <td colSpan={6} className="border-t border-edge bg-night/60 px-4 py-3">
                      <div className="grid gap-4 text-[13.5px] md:grid-cols-2">
                        <div>
                          <div className="mb-1 font-medium">Steps</div>
                          {steps.length ? (
                            <ol className="space-y-1">
                              {steps.map((s, i) => (
                                <li key={i} className="num flex justify-between gap-4">
                                  <span>{stepName[s.step] ?? s.step}{s.service ? `: ${String(s.service)}` : ""}</span>
                                  <span className="text-slate">{s.at_ms} ms</span>
                                </li>
                              ))}
                            </ol>
                          ) : (
                            <p className="text-slate">No step trace (logged by Make.com or an external scheduler).</p>
                          )}
                        </div>
                        <div>
                          <div className="mb-1 font-medium">Details</div>
                          <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-surface p-3 text-[12px] leading-relaxed text-ink/80">
                            {JSON.stringify({ run_id: r.run_id, ...Object.fromEntries(Object.entries(r.details ?? {}).filter(([k]) => k !== "steps")) }, null, 2)}
                          </pre>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Messages({ items }: { items: Notification[] }) {
  if (!items.length) return <Empty title="Nothing sent yet" />;
  return (
    <ul className="divide-y divide-edge">
      {items.map((n) => (
        <li key={n.id} className="py-3">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-[12.5px] text-slate">
            <Pill tone={n.kind === "alert" ? "failure" : n.kind === "draft" ? "info" : "neutral"}>{n.kind}</Pill>
            <span>{n.channel === "email" ? `To ${n.recipient}` : "#northwind-ops"}</span>
            <span>{timeAgo(n.created_at)}</span>
            <Pill tone={statusTone(n.status)}>{n.status}</Pill>
          </div>
          {n.subject && <div className="font-medium">{n.subject}</div>}
          <p className="line-clamp-4 whitespace-pre-line text-[13.5px] text-ink/85">{slackText(n.body)}</p>
        </li>
      ))}
    </ul>
  );
}

export default function Automations() {
  const toast = useToast();
  const [filter, setFilter] = useState<"all" | "failure">("all");
  const [channel, setChannel] = useState<"slack" | "email">("slack");
  const [failing, setFailing] = useState(false);
  const logs = useApi<LogRow[]>(`/api/automation/logs?limit=100${filter === "failure" ? "&status=failure" : ""}`, 10000);
  const stats = useApi<AutomationStats>("/api/automation/stats?days=7", 10000);
  const status = useApi<Status>("/api/status");
  const real = useStatus()?.data.mode === "real";
  const messages = useApi<Notification[]>(`/api/notifications?channel=${channel}&limit=40`, 10000);
  const { reload: r1 } = logs;
  const { reload: r2 } = stats;
  const { reload: r3 } = messages;
  const refresh = useCallback(() => { void r1(); void r2(); void r3(); }, [r1, r2, r3]);
  useOnDataChanged(refresh);

  async function forceFailure() {
    setFailing(true);
    try {
      const r = await api.post<{ run_id: string }>("/api/demo/forced-failure");
      sendRun(false, ["ads"]);
      world.set({ step: "errors" });
      toast("failure", `Forced failure logged (run ${r.run_id}) and the Slack alert was sent.`);
      dataChanged();
    } catch (e) {
      toast("failure", e instanceof Error ? e.message : String(e));
    } finally {
      setFailing(false);
    }
  }

  return (
    <>
      <Section shot="automation" side="right" wide>
        <Card>
          <CardTitle aside={real ? null : <button type="button" className={clsx(btn.secondary, "!text-[#B42318]")} disabled={failing} onClick={forceFailure}>{failing ? "Failing…" : "Force a failure"}</button>}>Automation</CardTitle>
          <p className="text-[15px] leading-relaxed text-[#3f444c]">
            Every workflow writes a success or failure row to the run log, and every failure posts a Slack alert.{real ? "" : " Force a failure and watch the red bead take the error route."}
          </p>
          {!stats.data ? (
            <Skeleton className="mt-4 h-28" />
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[460px] text-[14px]">
                <thead>
                  <tr className="text-left text-[12.5px] text-[#5B616B]">
                    <th className="pb-2 font-medium">Workflow, last 7 days</th>
                    <th className="pb-2 text-right font-medium">Worked</th>
                    <th className="pb-2 text-right font-medium">Failed</th>
                    <th className="pb-2 text-right font-medium">Last run</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.data.workflows.map((w) => (
                    <tr key={w.workflow} className="border-t border-black/[0.07]">
                      <td className="py-2.5 font-medium">{workflowName[w.workflow] ?? w.workflow}</td>
                      <td className="num py-2.5 text-right">{w.success}</td>
                      <td className={clsx("num py-2.5 text-right", w.failure > 0 && "font-semibold text-[#B42318]")}>{w.failure}</td>
                      <td className="py-2.5 text-right text-[#5B616B]">{w.last_run ? timeAgo(w.last_run) : "n/a"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {status.data && (
            <ul className="mt-5 flex flex-wrap gap-2 text-[12.5px]">
              {Object.entries(status.data.integrations).map(([k, v]) => {
                const live = v.startsWith("live") || v.startsWith("supabase");
                return (
                  <li key={k} title={v} className={clsx("rounded-full px-2.5 py-1 ring-1", live ? "bg-[#e7f6f2] text-[#0b5f52] ring-[#0f9f88]/20" : "bg-black/[0.03] text-[#5B616B] ring-black/[0.06]")}>
                    {integrationLabel[k] ?? k}: {live ? "live" : "demo"}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </Section>

      <Section shot="runs" wide>
        <Card>
          <CardTitle aside={<Segmented label="Show" value={filter} onChange={setFilter} options={[{ value: "all", label: "All runs" }, { value: "failure", label: "Failures" }]} />}>Run log</CardTitle>
          {logs.error && <ErrorNote message={logs.error} />}
          <div className="max-h-[52vh] overflow-y-auto">{!logs.data ? <Skeleton className="h-48" /> : logs.data.length ? <LogTable rows={logs.data} /> : <Empty title="No runs match" />}</div>
        </Card>
      </Section>

      <Section shot="home" wide>
        <Card>
          <CardTitle aside={<Segmented label="Channel" value={channel} onChange={setChannel} options={[{ value: "slack", label: "Slack" }, { value: "email", label: "Email" }]} />}>Messages sent</CardTitle>
          <div className="max-h-[52vh] overflow-y-auto">{messages.data ? <Messages items={messages.data} /> : <Skeleton className="h-40" />}</div>
        </Card>
      </Section>
    </>
  );
}
