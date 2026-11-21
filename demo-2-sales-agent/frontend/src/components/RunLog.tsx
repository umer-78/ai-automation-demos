import clsx from "clsx";
import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { Run, ToolCall } from "../lib/api";
import { seconds, TOOL_LABEL } from "../lib/format";
import { Chip, StatusChip } from "./ui";

type Step = { key: string; tool: string; ok: boolean; via: string; result: string; at: number };

function stepsOf(run: Run): Step[] {
  if (run.tools_called && run.tools_called.length) {
    return run.tools_called.map((t: ToolCall, i) => ({ key: `${i}`, tool: t.tool, ok: t.ok, via: t.via, result: t.result, at: t.at_ms }));
  }
  return (run.live_steps ?? []).map((s, i) => ({ key: `${i}`, tool: s.step, ok: s.ok !== false, via: s.via ?? "agent", result: s.result ?? "", at: s.at_ms }));
}

const VIA_LABEL: Record<string, string> = { agent: "AI", planner: "planner", fallback: "fallback" };

/** Streams the run's tool calls as they happen; afterwards shows the logged tool list. */
export default function RunLog({ run, compact = false }: { run: Run; compact?: boolean }) {
  const [all, setAll] = useState(false);
  const steps = stepsOf(run);
  const running = run.status === "running";
  const shown = all || !compact ? steps : steps.slice(-8);
  const failures = steps.filter((s) => !s.ok).length;
  return (
    <section className="panel overflow-hidden" aria-live="polite">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-rule-soft px-5 py-3.5">
        <h2 className="heading text-[16px]">{running ? "The agent is working" : "Last run"}</h2>
        <StatusChip status={run.status} />
        <Chip tone={run.mode === "live" ? "amber" : "neutral"}>{run.mode === "live" ? `Live AI${run.model ? `, ${run.model}` : ""}` : "Offline planner"}</Chip>
        <span className="text-[13px] text-ink-3">
          {`${steps.length} tool calls${failures ? `, ${failures} refused` : ""}${run.duration_ms !== null ? `, ${seconds(run.duration_ms)}` : ""}`}
        </span>
        <Link to={`/runs?run=${run.id}`} className="link ml-auto text-[13px] font-semibold">
          Open run log
        </Link>
      </header>
      {run.summary && !running && <p className="border-b border-rule-soft bg-sage-soft/50 px-5 py-3 text-[14px] text-ink">{run.summary}</p>}
      {run.outcome && !running && run.status !== "completed" && <p className="border-b border-rule-soft px-5 py-2.5 text-[13px] text-ink-2">{run.outcome}</p>}
      <ol className={clsx("divide-y divide-rule-soft", compact && "max-h-[340px] overflow-y-auto")}>
        <AnimatePresence initial={false}>
          {shown.map((s) => (
            <motion.li
              key={s.key}
              layout="position"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-start gap-3 px-5 py-2.5 text-[14px]"
            >
              {s.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-moss" aria-label="ok" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-crimson" aria-label="refused" />}
              <div className="min-w-0 flex-1">
                <span className="font-semibold">{TOOL_LABEL[s.tool] ?? s.tool}</span>
                {s.result && <span className={clsx("ml-2", s.ok ? "text-ink-2" : "text-crimson")}>{s.result}</span>}
              </div>
              <span className="shrink-0 text-[12px] text-ink-3">{VIA_LABEL[s.via] ?? s.via}</span>
              <span className="num w-14 shrink-0 text-right text-[12px] text-ink-3">{seconds(s.at)}</span>
            </motion.li>
          ))}
        </AnimatePresence>
        {running && (
          <li className="flex items-center gap-3 px-5 py-2.5 text-[14px] text-ink-3">
            <CircleDashed className="size-4 animate-spin" aria-hidden /> Working on the next step
          </li>
        )}
      </ol>
      {compact && steps.length > 8 && (
        <button onClick={() => setAll((v) => !v)} className="w-full border-t border-rule-soft px-5 py-2 text-left text-[13px] font-semibold text-ink-2 hover:bg-spruce/[0.03]">
          {all ? "Show the last 8 steps" : `Show all ${steps.length} steps`}
        </button>
      )}
    </section>
  );
}
