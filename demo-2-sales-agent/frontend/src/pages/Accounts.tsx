import { useCallback, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { AccountDrawer } from "../components/Drawers";
import { ErrorNote, FlagChip, ScoreBar, ScoreLegend, Skeleton, Tabs } from "../components/ui";
import type { Account } from "../lib/api";
import { moneyK, timeAgo } from "../lib/format";
import { useApi, useDataStatus, useOnDataChanged } from "../lib/hooks";
import { Card, CardTitle, Section } from "../world/Section";
import { world, useWorld } from "../world/store";

type Filter = "all" | "stalled" | "no_contact" | "upsell";
const STAGES = ["Prospect", "Discovery", "Proposal", "Customer"] as const;

export default function Accounts() {
  const [params, setParams] = useSearchParams();
  const filter = (params.get("flag") as Filter | null) ?? "all";
  const stage = params.get("stage") ?? "";
  const { data, error, reload } = useApi<Account[]>("/api/accounts");
  const status = useDataStatus();
  useOnDataChanged(useCallback(() => void reload(), [reload]));
  const open = useWorld((s) => s.account);
  useEffect(() => {
    world.set({ flag: filter === "all" ? null : filter });
    return () => world.set({ flag: null });
  }, [filter]);
  useEffect(() => {
    const id = Number(params.get("account"));
    if (id) {
      world.set({ account: id });
      const next = new URLSearchParams(params);
      next.delete("account");
      setParams(next, { replace: true });
    }
  }, [params, setParams]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: data?.length ?? 0, stalled: 0, no_contact: 0, upsell: 0 };
    for (const a of data ?? []) for (const f of a.flags ?? []) c[f] += 1;
    return c;
  }, [data]);
  const analysed = (data ?? []).some((a) => a.analyzed_at);
  const rows = (data ?? []).filter((a) => (filter === "all" || (a.flags ?? []).includes(filter)) && (!stage || a.stage === stage));
  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value && value !== "all") next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <Section shot="crm" wide>
      <Card>
        <CardTitle aside={<ScoreLegend />}>CRM accounts</CardTitle>
        <p className="text-[15px] leading-relaxed text-ink-2">
          {status?.mode === "real" ? `Your ${data?.length ?? ""} accounts.` : "Fifty fictional accounts across four stages."} On every run the agent flags stalled deals, accounts with no contact for 30+ days and likely upsells, scores each account and drafts the follow-ups. Each pillar is an account; the filter dims the rest.
        </p>
        {error && <ErrorNote message={error} />}
        {data && !analysed && <p className="mt-3 rounded-xl bg-amber-soft px-4 py-3 text-[14px]">These accounts have not been analysed yet. Run the agent to flag and score them.</p>}
        <div className="mt-4 flex flex-wrap items-end justify-between gap-3">
          <Tabs
            label="Flags"
            value={filter}
            onChange={(v) => setParam("flag", v)}
            options={[
              { value: "all", label: "All", count: counts.all },
              { value: "stalled", label: "Stalled", count: counts.stalled },
              { value: "no_contact", label: "No contact", count: counts.no_contact },
              { value: "upsell", label: "Upsell", count: counts.upsell },
            ]}
          />
          <label className="flex items-center gap-2 pb-2 text-[13.5px] text-ink-2">
            Stage
            <select className="field !w-auto !py-1.5" value={stage} onChange={(e) => setParam("stage", e.target.value)}>
              <option value="">All stages</option>
              {STAGES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>
        {!data ? (
          <Skeleton className="mt-4 h-96 w-full" />
        ) : (
          <ul className="-mx-2 mt-2 max-h-[56vh] divide-y divide-rule-soft overflow-y-auto pr-1">
            {rows.map((a) => (
              <li key={a.id}>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => world.set({ account: a.id })}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && world.set({ account: a.id })}
                  onMouseEnter={() => world.set({ hoverAccount: a.id })}
                  onMouseLeave={() => world.set({ hoverAccount: null })}
                  className="grid cursor-pointer gap-2 rounded-xl px-2 py-3 transition-colors hover:bg-black/[0.03] sm:grid-cols-[1fr_160px] sm:items-start"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="heading text-[15px]">{a.company}</span>
                      {(a.flags ?? []).map((f) => (
                        <FlagChip key={f} flag={f} />
                      ))}
                    </div>
                    <div className="text-[12.5px] text-ink-3">
                      {a.stage}, {moneyK(a.stage === "Customer" ? a.arr : a.deal_value)}, last contact {timeAgo(a.last_contact)}, owner {a.owner}
                    </div>
                  </div>
                  {a.score !== null ? <ScoreBar parts={a.score_parts} score={a.score} size="sm" /> : <span className="text-[13px] text-ink-3">Not scored</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <AccountDrawer id={open} onClose={() => world.set({ account: null })} />
    </Section>
  );
}
