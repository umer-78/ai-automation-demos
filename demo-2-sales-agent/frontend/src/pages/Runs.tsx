import clsx from "clsx";
import { BellRing } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import RunLog from "../components/RunLog";
import { Button, Chip, Empty, ErrorNote, PageHeader, Panel, Skeleton, StatusChip, useToast } from "../components/ui";
import { api, type LogRow, type Notification, type Overview, type Run } from "../lib/api";
import { count, seconds, timeAgo } from "../lib/format";
import { dataChanged, useApi, useOnDataChanged } from "../lib/hooks";

const WORKFLOW: Record<string, string> = {
  agent_run: "Agent run",
  agent_ai_call: "AI call",
  weekly_report: "Weekly report to Slack",
  forced_failure_check: "Deliberate test failure",
};

const AgentFlow3D = lazy(() => import("../components/AgentFlow3D"));

const slackText = (text: string) =>
  text.replace(/<[^|>]+\|([^>]+)>/g, "$1").replace(/[*`]/g, "").replace(/:[a-z_]+:/g, "").replace(/^> /gm, "").trim();

export default function Runs() {
  const [params, setParams] = useSearchParams();
  const { data: runs, error, reload } = useApi<Run[]>("/api/runs");
  const { data: log, reload: reloadLog } = useApi<LogRow[]>("/api/automation-log");
  const { data: feed, reload: reloadFeed } = useApi<Notification[]>("/api/notifications");
  const { data: overview, reload: reloadOverview } = useApi<Overview>("/api/overview");
  const toast = useToast();
  const [failing, setFailing] = useState(false);
  useOnDataChanged(
    useCallback(() => {
      void reload();
      void reloadLog();
      void reloadFeed();
      void reloadOverview();
    }, [reload, reloadLog, reloadFeed, reloadOverview]),
  );
  const selected = params.get("run") ?? runs?.[0]?.id ?? null;
  const { data: run, reload: reloadRun } = useApi<Run>(selected ? `/api/runs/${selected}` : null);
  useEffect(() => {
    if (run?.status !== "running") return;
    const id = window.setInterval(() => void reloadRun(), 1000);
    return () => window.clearInterval(id);
  }, [run?.status, reloadRun]);

  const testFailure = async () => {
    setFailing(true);
    try {
      await api.post("/api/automation/test-failure");
      toast("info", "Failure logged and the Slack alert was raised. See below.");
      dataChanged();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setFailing(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Runs and logs"
        description="Every agent run is stored with each tool it called, what came back, tokens and cost. Every automation writes success or failure to the automation log, and failures raise a Slack alert."
        actions={
          <Button icon={<BellRing className="size-4" />} busy={failing} onClick={() => void testFailure()}>
            Test a failure alert
          </Button>
        }
      />
      {error && <ErrorNote message={error} />}
      {run && (
        <Suspense fallback={<Skeleton className="h-[436px] w-full" />}>
          <AgentFlow3D run={run} counts={overview?.counts} />
        </Suspense>
      )}
      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <Panel title="Agent runs" padded={false}>
          {!runs ? (
            <Skeleton className="m-5 h-40" />
          ) : runs.length === 0 ? (
            <p className="px-5 py-6 text-[14px] text-ink-3">No runs yet. Click Run agent.</p>
          ) : (
            <ul className="max-h-[640px] divide-y divide-rule-soft overflow-y-auto">
              {runs.map((r) => (
                <li key={r.id}>
                  <button
                    onClick={() => setParams({ run: r.id })}
                    className={clsx("w-full border-l-[3px] px-4 py-3 text-left transition-colors", r.id === selected ? "border-amber bg-paper" : "border-transparent hover:bg-spruce/[0.03]")}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[14px] font-semibold">{timeAgo(r.started_at)}</span>
                      <StatusChip status={r.status} />
                    </div>
                    <div className="mt-1 text-[12.5px] text-ink-3">
                      {`${r.mode === "live" ? "Live AI" : "Offline"}, ${r.trigger}, ${seconds(r.duration_ms)}, ${r.tool_call_count} tools, ${r.leads_scored} leads, ${r.drafts_created + r.followups_created} drafts`}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <div className="min-w-0 space-y-4">
          {run ? (
            <>
              <div className="panel grid grid-cols-2 gap-4 px-5 py-4 text-[14px] sm:grid-cols-4">
                <div>
                  <div className="text-ink-3">Tokens</div>
                  <div className="num font-bold">{run.mode === "live" ? count(run.tokens) : "0 (offline)"}</div>
                </div>
                <div>
                  <div className="text-ink-3">Cost estimate</div>
                  <div className="num font-bold">{run.mode === "live" ? `$${run.cost_usd.toFixed(3)}` : "Free (offline)"}</div>
                </div>
                <div>
                  <div className="text-ink-3">Model turns</div>
                  <div className="num font-bold">{run.mode === "live" ? run.turns : "n/a"}</div>
                </div>
                <div>
                  <div className="text-ink-3">Feedback in prompt</div>
                  <div className="num font-bold">{run.feedback_ids?.length ?? 0} items</div>
                </div>
              </div>
              <RunLog run={run} />
              {run.context_feedback && run.context_feedback !== "No feedback yet." && (
                <Panel title="Reviewer feedback this run received">
                  <blockquote className="whitespace-pre-wrap border-l-[3px] border-amber pl-4 text-[14px] text-ink-2">{run.context_feedback}</blockquote>
                </Panel>
              )}
            </>
          ) : runs && runs.length === 0 ? (
            <Empty title="No runs yet">The run log appears here, step by step, as soon as you start the agent.</Empty>
          ) : (
            <Skeleton className="h-80 w-full" />
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Automation log" subtitle="Success and failure for every automation" padded={false}>
          <ul className="max-h-[420px] divide-y divide-rule-soft overflow-y-auto">
            {(log ?? []).map((row) => (
              <li key={row.id} className="px-5 py-2.5 text-[14px]">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusChip status={row.status} />
                  <span className="font-semibold">{WORKFLOW[row.workflow] ?? row.workflow}</span>
                  <span className="text-[12.5px] text-ink-3">
                    {row.source}, {timeAgo(row.created_at)}
                    {row.duration_ms !== null ? `, ${seconds(row.duration_ms)}` : ""}
                  </span>
                </div>
                {row.error && <p className="mt-0.5 text-[13px] text-crimson">{row.error}</p>}
              </li>
            ))}
            {log && log.length === 0 && <li className="px-5 py-6 text-[14px] text-ink-3">Nothing logged yet.</li>}
          </ul>
        </Panel>
        <Panel title="Slack feed" subtitle="Internal channel only. Shown here when no Slack workspace is connected." padded={false}>
          <ul className="max-h-[420px] divide-y divide-rule-soft overflow-y-auto">
            {(feed ?? []).map((n) => (
              <li key={n.id} className="px-5 py-2.5 text-[14px]">
                <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-ink-3">
                  <Chip tone={n.kind === "alert" ? "crimson" : n.kind === "report" ? "cobalt" : "sage"}>{n.kind}</Chip>
                  <span>
                    {n.recipient}, {n.status}, {timeAgo(n.created_at)}
                  </span>
                </div>
                <p className="mt-1 whitespace-pre-wrap">{slackText(n.body)}</p>
              </li>
            ))}
            {feed && feed.length === 0 && <li className="px-5 py-6 text-[14px] text-ink-3">No messages yet.</li>}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
