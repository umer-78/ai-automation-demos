import { SERVICE_BRANCH } from "../components/flowNodes";
import { Card, CardTitle, Section, btn } from "../world/Section";
import { sendRun, useWorld, world, type Shot } from "../world/store";
import { clientOrder, pedestalHeight, pedestalPos } from "../world/layout";
import clsx from "clsx";
import { CheckCircle2, Circle, CircleSlash } from "lucide-react";
import { useCallback, useMemo, useState, useEffect } from "react";
import OnboardingDrawer from "../components/OnboardingDrawer";
import { Button, Drawer, Empty, ErrorNote, Pill, Segmented, Skeleton, statusTone, useToast } from "../components/ui";
import { api, type Client, type LogRow, type Overview, type RunStatus, type Task } from "../lib/api";
import { money, shortDate, timeAgo, workflowName } from "../lib/format";
import { dataChanged, useApi, useOnDataChanged } from "../lib/hooks";

type Filter = "all" | "active" | "onboarding" | "archived";

function TaskIcon({ status }: { status: Task["status"] }) {
  if (status === "done") return <CheckCircle2 className="size-4 text-aurora-ink" aria-label="done" />;
  if (status === "closed") return <CircleSlash className="size-4 text-slate" aria-label="closed" />;
  return <Circle className="size-4 text-faint" aria-label="open" />;
}

function ClientDrawer({ clientId, onClose }: { clientId: number | null; onClose: () => void }) {
  const toast = useToast();
  const { data, error, reload } = useApi<{ client: Client; tasks: Task[]; runs: LogRow[] }>(clientId ? `/api/clients/${clientId}` : null);
  const [churning, setChurning] = useState(false);

  async function churn() {
    if (!data) return;
    setChurning(true);
    try {
      const { run_id } = await api.post<{ run_id: string }>(`/api/clients/${data.client.id}/churn`);
      for (let i = 0; i < 30; i++) {
        const r = await api.get<RunStatus>(`/api/automation/runs/${run_id}`).catch(() => null);
        if (r && r.status !== "running") break;
        await new Promise((res) => setTimeout(res, 600));
      }
      toast("success", `${data.client.name} was off-boarded: tasks closed, client archived, summary posted to Slack.`);
      await reload();
      dataChanged();
    } catch (e) {
      toast("failure", e instanceof Error ? e.message : String(e));
    } finally {
      setChurning(false);
    }
  }

  const grouped = useMemo(() => {
    const out: Record<string, Task[]> = {};
    for (const t of data?.tasks ?? []) (out[t.service] ??= []).push(t);
    return out;
  }, [data]);

  const c = data?.client;
  return (
    <Drawer open={clientId !== null} onClose={onClose} title={c?.name ?? "Client"} width={600}>
      {error && <ErrorNote message={error} />}
      {!c ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="space-y-7">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={statusTone(c.status)}>{c.status}</Pill>
            {c.services.map((s) => <Pill key={s}>{s}</Pill>)}
            <span className="text-[13px] text-slate">Account manager: {c.manager ?? "unassigned"}</span>
          </div>

          <section>
            <div className="mb-2 flex items-baseline justify-between">
              <h3 className="heading text-[16px]">Client brief</h3>
              {c.brief_data && <span className="text-[12.5px] text-slate">{c.brief_data.generated_by === "ai" ? "Written by the AI model" : "Offline template"}</span>}
            </div>
            {c.brief_data ? (
              <div className="space-y-3 text-[14.5px]">
                <p>{c.brief_data.summary}</p>
                <div><div className="font-medium">Audience</div><p className="text-slate">{c.brief_data.audience}</p></div>
                <div><div className="font-medium">Tone of voice</div><p className="text-slate">{c.brief_data.tone}</p></div>
                <div>
                  <div className="font-medium">3 quick wins</div>
                  <ol className="mt-1 list-decimal space-y-1 pl-5 text-slate">
                    {c.brief_data.quick_wins.map((w) => <li key={w}>{w}</li>)}
                  </ol>
                </div>
                {!!c.brief_data.kickoff_questions?.length && (
                  <div>
                    <div className="font-medium">Confirm at kickoff</div>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-slate">
                      {c.brief_data.kickoff_questions.map((q) => <li key={q}>{q}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-slate">No brief yet. It is written during onboarding.</p>
            )}
          </section>

          <section>
            <h3 className="heading mb-2 text-[16px]">Checklists</h3>
            {Object.keys(grouped).length === 0 && <p className="text-slate">No tasks yet.</p>}
            <div className="space-y-4">
              {Object.entries(grouped).map(([service, tasks]) => (
                <div key={service}>
                  <div className="mb-1 text-[13px] font-medium text-slate">{service}</div>
                  <ul className="space-y-1.5">
                    {tasks.map((t) => (
                      <li key={t.id} className="flex items-start gap-2.5 text-[14px]">
                        <span className="mt-0.5"><TaskIcon status={t.status} /></span>
                        <span className={clsx(t.status !== "open" && "text-slate line-through decoration-slate/40")}>{t.title}</span>
                        {t.due_date && t.status === "open" && <span className="ml-auto shrink-0 text-[12.5px] text-slate">due {shortDate(t.due_date)}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="heading mb-2 text-[16px]">Automation runs</h3>
            {data.runs.length === 0 ? (
              <p className="text-slate">No runs for this client yet.</p>
            ) : (
              <ul className="divide-y divide-edge">
                {data.runs.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-3 py-2 text-[14px]">
                    <span>{workflowName[r.workflow] ?? r.workflow}</span>
                    <span className="flex items-center gap-3">
                      <span className="text-[12.5px] text-slate">{timeAgo(r.created_at)}</span>
                      <Pill tone={statusTone(r.status)}>{r.status}</Pill>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-lg border border-edge p-4">
            <h3 className="font-medium">Off-board this client</h3>
            <p className="mt-1 text-[13.5px] text-slate">Same as setting Status to Churned in Airtable: closes open tasks, archives the client and posts a summary to Slack.</p>
            <Button className="mt-3" variant="danger" busy={churning} disabled={c.status === "archived"} onClick={churn}>
              {c.status === "archived" ? "Already archived" : "Mark as churned"}
            </Button>
          </section>
        </div>
      )}
    </Drawer>
  );
}

export default function Clients() {
  const [filter, setFilter] = useState<Filter>("all");
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const clients = useApi<Client[]>("/api/clients");
  const overview = useApi<Overview>("/api/metrics/overview?days=30");
  const { reload: reloadClients } = clients;
  const { reload: reloadOverview } = overview;
  const refresh = useCallback(() => {
    void reloadClients();
    void reloadOverview();
  }, [reloadClients, reloadOverview]);
  useOnDataChanged(refresh);

  // the pillars in the world and this list select the same client
  const picked = useWorld((s) => s.focusClient);
  useEffect(() => {
    if (picked != null) setSelected(picked);
  }, [picked]);
  useEffect(() => () => world.set({ focusClient: null }), []);
  const pick = (id: number | null) => {
    setSelected(id);
    world.set({ focusClient: id });
  };

  const perf = useMemo(() => Object.fromEntries((overview.data?.clients ?? []).map((c) => [c.client_id, c])), [overview.data]);
  const rows = (clients.data ?? []).filter((c) => filter === "all" || c.status === filter);
  const order = clientOrder(overview.data?.clients ?? null);
  const focus = useMemo<Shot | null>(() => {
    const i = order.findIndex((c) => c.client_id === selected);
    if (i < 0) return null;
    const [x, , z] = pedestalPos(i, order.length);
    const H = pedestalHeight(order[i].spend, Math.max(1, ...order.map((c) => c.spend)));
    return { pos: [x + 2.6, H + 4.2, z + 7.4], target: [x, H * 0.55, z], shift: 0.17, zone: "clients" };
  }, [order, selected]);

  return (
    <>
      <Section shot="clients" focus={focus} wide>
        <Card>
          <CardTitle aside={<button type="button" className={btn.primary} onClick={() => setAdding(true)}>Add a client</button>}>Clients</CardTitle>
          <p className="text-[15px] leading-relaxed text-[#3f444c]">
            Every client the team manages. Rows added in Airtable, or with the form, are onboarded on their own. Pick a client here or click its pillar: the taller the pillar, the more they spent in the last 30 days.
          </p>
          <div className="mt-4">
            <Segmented
              label="Filter clients by status"
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: "All" },
                { value: "active", label: "Active" },
                { value: "onboarding", label: "Onboarding" },
                { value: "archived", label: "Archived" },
              ]}
            />
          </div>
          {clients.error && <ErrorNote message={clients.error} />}
          <ul className="mt-3 max-h-[46vh] divide-y divide-black/[0.07] overflow-y-auto pr-1">
            {!clients.data && <li className="py-3"><Skeleton className="h-24" /></li>}
            {rows.map((c) => {
              const p = perf[c.id];
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => pick(c.id)}
                    className={clsx("flex w-full items-center gap-3 rounded-xl px-2 py-3 text-left transition-colors hover:bg-black/[0.035]", selected === c.id && "bg-black/[0.05]")}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2 font-medium">
                        {c.name}
                        {p?.alerts ? <span aria-label="Open alert" className="inline-block size-1.5 rounded-full bg-[#e5484d]" /> : null}
                      </span>
                      <span className="block truncate text-[12.5px] text-[#5B616B]">
                        {c.industry}, {c.services.join(", ")}
                      </span>
                    </span>
                    <Pill tone={statusTone(c.status)}>{c.status}</Pill>
                    <span className="num w-24 text-right text-[13.5px]">{p ? money(p.spend) : "no spend yet"}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          {clients.data && rows.length === 0 && <Empty title="No clients match this filter" />}
        </Card>
      </Section>
      <OnboardingDrawer open={adding} onClose={() => setAdding(false)} onFinished={(ok, services) => sendRun(ok, services.map((x) => SERVICE_BRANCH[x]).filter(Boolean))} />
      <ClientDrawer clientId={selected} onClose={() => pick(null)} />
    </>
  );
}
