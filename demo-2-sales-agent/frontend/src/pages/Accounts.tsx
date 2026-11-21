import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AccountDrawer } from "../components/Drawers";
import { ErrorNote, FlagChip, PageHeader, ScoreBar, ScoreLegend, Skeleton, Tabs } from "../components/ui";
import type { Account } from "../lib/api";
import { moneyK, timeAgo } from "../lib/format";
import { useApi, useOnDataChanged } from "../lib/hooks";

type Filter = "all" | "stalled" | "no_contact" | "upsell";
const STAGES = ["Prospect", "Discovery", "Proposal", "Customer"] as const;

export default function Accounts() {
  const [params, setParams] = useSearchParams();
  const filter = (params.get("flag") as Filter | null) ?? "all";
  const stage = params.get("stage") ?? "";
  const { data, error, reload } = useApi<Account[]>("/api/accounts");
  useOnDataChanged(useCallback(() => void reload(), [reload]));
  const [open, setOpen] = useState<number | null>(null);

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
    <div>
      <PageHeader
        title="CRM accounts"
        description="Fifty fictional accounts across four stages. On every run the agent flags stalled deals, accounts with no contact for 30+ days and likely upsells, scores each account and drafts the follow-ups."
        actions={<ScoreLegend />}
      />
      {error && <ErrorNote message={error} />}
      {data && !analysed && (
        <p className="mb-4 rounded-lg border border-amber/40 bg-amber-soft/60 px-4 py-3 text-[14px]">These accounts have not been analysed yet. Run the agent to flag and score them.</p>
      )}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Tabs
          label="Flags"
          value={filter}
          onChange={(v) => setParam("flag", v)}
          options={[
            { value: "all", label: "All", count: counts.all },
            { value: "stalled", label: "Stalled", count: counts.stalled },
            { value: "no_contact", label: "No contact 30+ days", count: counts.no_contact },
            { value: "upsell", label: "Likely upsell", count: counts.upsell },
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
        <Skeleton className="mt-6 h-96 w-full" />
      ) : (
        <div className="panel mt-6 overflow-x-auto">
          <table className="w-full min-w-[900px] text-[14px]">
            <thead className="table-head">
              <tr>
                <th className="w-[210px]">Score</th>
                <th>Account</th>
                <th>Stage</th>
                <th>Value</th>
                <th>Last contact</th>
                <th>Flags</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id} className="table-row cursor-pointer transition-colors hover:bg-spruce/[0.03]" onClick={() => setOpen(a.id)}>
                  <td>{a.score !== null ? <ScoreBar parts={a.score_parts} score={a.score} size="sm" /> : <span className="text-ink-3">Not scored</span>}</td>
                  <td>
                    <button className="heading text-left text-[15px] hover:underline" onClick={() => setOpen(a.id)}>
                      {a.company}
                    </button>
                    <div className="text-[12.5px] text-ink-3">
                      {a.industry}, owner {a.owner}
                    </div>
                  </td>
                  <td>{a.stage}</td>
                  <td className="num">{moneyK(a.stage === "Customer" ? a.arr : a.deal_value)}</td>
                  <td>{timeAgo(a.last_contact)}</td>
                  <td>
                    <div className="flex flex-wrap gap-1.5">
                      {(a.flags ?? []).map((f) => (
                        <FlagChip key={f} flag={f} />
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AccountDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}
