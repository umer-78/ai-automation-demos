import { ExternalLink } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { LeadDrawer } from "../components/Drawers";
import { RunButton } from "../components/Layout";
import { Empty, ErrorNote, ScoreBar, ScoreLegend, Skeleton, StatusChip, Tabs } from "../components/ui";
import type { Lead } from "../lib/api";
import { CATEGORY_LABEL, hostOf, shortDate, SIGNAL_LABEL } from "../lib/format";
import { useApi, useOnDataChanged } from "../lib/hooks";
import { Card, CardTitle, Section } from "../world/Section";
import { world, useWorld } from "../world/store";

type Filter = "all" | "new" | "drafted" | "approved" | "contacted" | "excluded";
const FILTER_LABEL: Record<Filter, string> = { all: "All", new: "New", drafted: "In queue", approved: "Approved", contacted: "Contacted", excluded: "Excluded" };

export default function Leads() {
  const { data, error, reload } = useApi<Lead[]>("/api/leads");
  useOnDataChanged(useCallback(() => void reload(), [reload]));
  const [filter, setFilter] = useState<Filter>("all");
  const [params, setParams] = useSearchParams();
  const open = useWorld((s) => s.lead);
  useEffect(() => {
    const id = Number(params.get("lead"));
    if (id) {
      world.set({ lead: id });
      params.delete("lead");
      setParams(params, { replace: true });
    }
  }, [params, setParams]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: data?.length ?? 0 };
    for (const l of data ?? []) c[l.status] = (c[l.status] ?? 0) + 1;
    return c;
  }, [data]);
  const rows = (data ?? []).filter((l) => filter === "all" || l.status === filter);

  return (
    <Section shot="leads" side="right" wide>
      <Card>
        <CardTitle aside={<ScoreLegend />}>Leads</CardTitle>
        <p className="text-[15px] leading-relaxed text-ink-2">
          Real companies the agent found in public sources, each saved with its source link and a one-line reason. Scores come from the ideal customer profile, so the same company always scores the same way. Point at a row to find it on the radar.
        </p>
        {error && <ErrorNote message={error} />}
        <div className="mt-4">
          <Tabs label="Lead status" value={filter} onChange={setFilter} options={(Object.keys(FILTER_LABEL) as Filter[]).map((f) => ({ value: f, label: FILTER_LABEL[f], count: counts[f] ?? 0 }))} />
        </div>
        {!data ? (
          <Skeleton className="mt-4 h-96 w-full" />
        ) : data.length === 0 ? (
          <div className="mt-4">
            <Empty title="No leads yet" action={<RunButton />}>
              The agent searches the web for companies that match the ideal customer profile and have a recent buying signal.
            </Empty>
          </div>
        ) : (
          <ul className="-mx-2 mt-2 max-h-[58vh] divide-y divide-rule-soft overflow-y-auto pr-1">
            {rows.map((l) => {
              const fact = l.facts[0];
              return (
                <li key={l.id}>
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => world.set({ lead: l.id })}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && world.set({ lead: l.id })}
                    onMouseEnter={() => world.set({ hoverLead: l.id })}
                    onMouseLeave={() => world.set({ hoverLead: null })}
                    className="grid cursor-pointer gap-2 rounded-xl px-2 py-3 transition-colors hover:bg-black/[0.03] sm:grid-cols-[1fr_170px] sm:items-start"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="heading text-[15px]">{l.company}</span>
                        <StatusChip status={l.status} />
                      </div>
                      <div className="text-[12.5px] text-ink-3">
                        {CATEGORY_LABEL[l.category] ?? l.category}, {SIGNAL_LABEL[fact?.type ?? "news"]}{" "}
                        <a href={l.source_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="link inline-flex items-center gap-1">
                          {hostOf(l.source_url)}, {shortDate(fact?.date)} <ExternalLink className="size-3" aria-hidden />
                        </a>
                      </div>
                      <p className="mt-1 line-clamp-2 text-[14px] text-ink-2">{l.reason}</p>
                    </div>
                    <ScoreBar parts={l.score_parts} score={l.score} size="sm" dimmed={l.status === "excluded"} />
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      <LeadDrawer id={open} onClose={() => world.set({ lead: null })} />
    </Section>
  );
}
