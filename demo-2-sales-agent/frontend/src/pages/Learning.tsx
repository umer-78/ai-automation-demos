import clsx from "clsx";
import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { Chip, Empty, ErrorNote, PageHeader, Panel, Skeleton, Tilt } from "../components/ui";
import type { AgentContext, DraftStats, Learning as LearningData } from "../lib/api";
import { LESSON_LABEL, pct, shortDate, timeAgo } from "../lib/format";
import { useApi, useOnDataChanged } from "../lib/hooks";

function DraftColumn({ label, d, tone }: { label: string; d: DraftStats; tone: "before" | "after" }) {
  return (
    <div className="flex min-w-0 flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-[13px]">
        <span className={clsx("font-bold", tone === "before" ? "text-crimson" : "text-moss")}>{label}</span>
        <span className="num text-ink-3">{d.words} words</span>
        <span className="text-ink-3">{d.meeting_ask ? "asks for a meeting" : "no meeting ask"}</span>
      </div>
      <Tilt className="flex flex-1" max={2.5}>
        <div className="sheet flex-1 px-4 py-3">
          <div className="mb-2 text-[14px] font-semibold">{d.subject}</div>
          <div className="whitespace-pre-wrap text-[14px] leading-relaxed text-ink-2">{d.body}</div>
        </div>
      </Tilt>
      {d.lessons_applied.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {d.lessons_applied.filter((k) => LESSON_LABEL[k]).map((k) => (
            <Chip key={k} tone="sage">
              {LESSON_LABEL[k]}
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

function RunTrend({ runs }: { runs: LearningData["runs"] }) {
  if (runs.length < 1) return null;
  const max = Math.max(...runs.map((r) => r.avg_words), 1);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-[14px]">
        <thead className="table-head">
          <tr>
            <th>Run</th>
            <th>Feedback in prompt</th>
            <th className="w-[38%]">Average first email length</th>
            <th>Meeting asks</th>
            <th>Approval rate</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r, i) => (
            <tr key={r.run_id} className="table-row">
              <td>
                <Link to={`/runs?run=${r.run_id}`} className="link font-semibold">
                  Run {i + 1}
                </Link>
                <div className="text-[12.5px] text-ink-3">{timeAgo(r.started_at)}, {r.mode}</div>
              </td>
              <td className="num">
                {r.feedback_in_context} items, {r.rules_in_context} rules
              </td>
              <td>
                <div className="flex items-center gap-2">
                  <div className="h-2 flex-1 rounded-full bg-spruce/[0.07]">
                    <div className="h-2 rounded-full bg-spruce" style={{ width: `${(r.avg_words / max) * 100}%` }} />
                  </div>
                  <span className="num w-16 text-right">{r.avg_words} words</span>
                </div>
              </td>
              <td className="num">
                {r.meeting_asks} of {r.drafts}
              </td>
              <td className="num">{r.approval_rate === null ? "not reviewed" : pct(r.approval_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Learning() {
  const { data, error, reload } = useApi<LearningData>("/api/learning");
  const { data: ctx, reload: reloadCtx } = useApi<AgentContext>("/api/agent/context");
  useOnDataChanged(useCallback(() => {
    void reload();
    void reloadCtx();
  }, [reload, reloadCtx]));
  const [showPrompt, setShowPrompt] = useState(false);

  return (
    <div className="space-y-6">
      <PageHeader
        title="How the agent learns from you"
        description="Every approve, edit and reject is stored. The next run gets the last 20 of them in its prompt, plus the rules they add up to. The draft checks enforce those rules, so the change is visible, not hoped for."
      />
      {error && <ErrorNote message={error} />}
      {!data ? (
        <Skeleton className="h-80 w-full" />
      ) : (
        <>
          <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
            <Panel
              title="What the next run will read"
              subtitle={`${data.feedback.length} feedback item${data.feedback.length === 1 ? "" : "s"}, newest first`}
              action={
                ctx && (
                  <button className="link text-[13px] font-semibold" onClick={() => setShowPrompt((v) => !v)}>
                    {showPrompt ? "Hide the full prompt" : "Show the full prompt"}
                  </button>
                )
              }
            >
              {data.feedback.length === 0 ? (
                <Empty title="No feedback yet">
                  Approve, edit or reject drafts in the <Link to="/approvals" className="link">approval queue</Link>. Your reasons appear here and go into the next run.
                </Empty>
              ) : (
                <blockquote className="whitespace-pre-wrap border-l-[3px] border-amber pl-4 text-[14px] leading-relaxed text-ink-2">{data.context_block}</blockquote>
              )}
              {showPrompt && ctx && (
                <pre className="mt-4 max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg bg-spruce p-4 font-[inherit] text-[13px] leading-relaxed text-[#dcebe4]">{ctx.system_prompt}</pre>
              )}
            </Panel>
            <Panel title="Rules learned from feedback" subtitle={`First emails capped at ${data.lessons.max_words} words`}>
              {data.lessons.rules.length === 0 ? (
                <p className="text-[14px] text-ink-3">No rules yet. A rejection reason like "too long" or "skip big enterprises" becomes a rule here.</p>
              ) : (
                <ul className="space-y-3">
                  {data.lessons.rules.map((r) => (
                    <li key={r.key} className="text-[14.5px]">
                      <div className="flex items-start gap-2">
                        <Chip tone="sage">{LESSON_LABEL[r.key] ?? r.key}</Chip>
                        <span>{r.text}</span>
                      </div>
                      <div className="mt-0.5 pl-1 text-[12.5px] text-ink-3">From feedback #{r.feedback_ids.join(", #")}</div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          <Panel title="Before and after" subtitle="A rejected draft and the agent's next draft for the same company">
            {data.pairs.length === 0 ? (
              <Empty title="No rewrites yet">
                Reject a first email with a reason (for example "too long, mention pricing"), then run the agent again. The new draft for that company appears here next to the old one.
              </Empty>
            ) : (
              <div className="space-y-10">
                {data.pairs.map((p) => (
                  <div key={p.after.id}>
                    <div className="mb-3 flex flex-wrap items-baseline gap-x-3">
                      <h3 className="heading text-[18px]">{p.company}</h3>
                      {p.feedback?.reason && (
                        <span className="text-[14px] text-ink-2">
                          Rejected with: <q className="font-semibold text-ink">{p.feedback.reason}</q>
                        </span>
                      )}
                      <span className="text-[12.5px] text-ink-3">{shortDate(p.after.created_at)}</span>
                    </div>
                    <div className="grid gap-5 md:grid-cols-2">
                      <DraftColumn label="Before" d={p.before} tone="before" />
                      <DraftColumn label="After" d={p.after} tone="after" />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Run by run" padded={false}>
            {data.runs.length === 0 ? <p className="px-5 py-6 text-[14px] text-ink-3">No runs yet.</p> : <RunTrend runs={data.runs} />}
          </Panel>
        </>
      )}
    </div>
  );
}
