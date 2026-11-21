import { ExternalLink } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { LeadDrawer } from "../components/Drawers";
import { RunButton } from "../components/Layout";
import { Empty, ErrorNote, PageHeader, ScoreBar, ScoreLegend, Skeleton, StatusChip, Tabs } from "../components/ui";
import type { Lead } from "../lib/api";
import { CATEGORY_LABEL, hostOf, shortDate, SIGNAL_LABEL } from "../lib/format";
import { useApi, useOnDataChanged } from "../lib/hooks";

type Filter = "all" | "new" | "drafted" | "approved" | "contacted" | "excluded";

export default function Leads() {
  const { data, error, reload } = useApi<Lead[]>("/api/leads");
  useOnDataChanged(useCallback(() => void reload(), [reload]));
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<number | null>(null);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: data?.length ?? 0 };
    for (const l of data ?? []) c[l.status] = (c[l.status] ?? 0) + 1;
    return c;
  }, [data]);
  const rows = (data ?? []).filter((l) => filter === "all" || l.status === filter);

  return (
    <div>
      <PageHeader
        title="Leads"
        description="Real companies the agent found in public sources, each saved with the source link and a one-line reason. Scores come from the ideal customer profile, so the same company always scores the same way."
        actions={<ScoreLegend />}
      />
      {error && <ErrorNote message={error} />}
      <Tabs
        label="Lead status"
        value={filter}
        onChange={setFilter}
        options={(["all", "new", "drafted", "approved", "contacted", "excluded"] as Filter[]).map((f) => ({
          value: f,
          label: { all: "All", new: "New", drafted: "Draft in queue", approved: "Approved", contacted: "Contacted", excluded: "Excluded" }[f],
          count: counts[f] ?? 0,
        }))}
      />
      {!data ? (
        <Skeleton className="mt-6 h-96 w-full" />
      ) : data.length === 0 ? (
        <div className="mt-6">
          <Empty title="No leads yet" action={<RunButton />}>
            The agent searches the web for companies that match the ideal customer profile and have a recent buying signal.
          </Empty>
        </div>
      ) : (
        <div className="panel mt-6 overflow-x-auto">
          <table className="w-full min-w-[860px] text-[14px]">
            <thead className="table-head">
              <tr>
                <th className="w-[230px]">Score</th>
                <th>Company</th>
                <th>Signal</th>
                <th>Why now</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((l) => {
                const fact = l.facts[0];
                return (
                  <tr key={l.id} className="table-row cursor-pointer transition-colors hover:bg-spruce/[0.03]" onClick={() => setOpen(l.id)}>
                    <td>
                      <ScoreBar parts={l.score_parts} score={l.score} size="sm" dimmed={l.status === "excluded"} />
                    </td>
                    <td>
                      <button className="heading text-left text-[15px] hover:underline" onClick={() => setOpen(l.id)}>
                        {l.company}
                      </button>
                      <div className="text-[12.5px] text-ink-3">{CATEGORY_LABEL[l.category] ?? l.category}</div>
                    </td>
                    <td className="w-[220px]">
                      <div>{SIGNAL_LABEL[fact?.type ?? "news"]}</div>
                      <a href={l.source_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="link inline-flex items-center gap-1 text-[12.5px]">
                        {hostOf(l.source_url)}, {shortDate(fact?.date)} <ExternalLink className="size-3" aria-hidden />
                      </a>
                    </td>
                    <td className="max-w-[360px] text-ink-2">{l.reason}</td>
                    <td>
                      <StatusChip status={l.status} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <LeadDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}
