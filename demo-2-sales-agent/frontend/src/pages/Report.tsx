import { Download, ExternalLink, Printer } from "lucide-react";
import { useCallback } from "react";
import { Link } from "react-router-dom";
import { Button, ErrorNote, Skeleton } from "../components/ui";
import { api, PREVIEW, type Report as ReportData, type ReportAccount } from "../lib/api";
import { count, hostOf, moneyK, pct, shortDate } from "../lib/format";
import { useApi, useOnDataChanged } from "../lib/hooks";

function AccountList({ title, rows, empty }: { title: string; rows: ReportAccount[]; empty: string }) {
  return (
    <section className="break-inside-avoid">
      <h3 className="mb-2 flex items-baseline gap-2 font-memo text-[19px] font-[620]">
        {title} <span className="num text-[14px] font-semibold text-ink-3">{rows.length}</span>
      </h3>
      {rows.length === 0 ? (
        <p className="text-[14px] text-ink-3">{empty}</p>
      ) : (
        <ul className="space-y-2 text-[14px]">
          {rows.map((a) => (
            <li key={a.id}>
              <span className="font-semibold">{a.company}</span>
              <span className="text-ink-3">
                {" "}
                ({a.stage}, {moneyK(a.value)}, {a.owner})
              </span>
              <div className="text-ink-2">{Object.values(a.why).join(" ")}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function Report() {
  const { data, error, reload } = useApi<ReportData>("/api/report/weekly");
  useOnDataChanged(useCallback(() => void reload(), [reload]));

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Skeleton className="h-[700px] w-full" />;
  const r = data.reviews;

  return (
    <div>
      <div className="no-print mb-6 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[14px] text-ink-2">Built from live data each time you open it. Generated {new Date(data.generated_at).toLocaleString("en-GB")}.</p>
        {!PREVIEW && (
          <div className="flex gap-2">
            <a href={api.url("/api/report/weekly.md")} className="inline-flex h-10 items-center gap-2 rounded-lg border border-rule bg-sheet px-4 text-[14px] font-semibold hover:border-ink-3/50">
              <Download className="size-4" /> Markdown
            </a>
            <Button variant="dark" icon={<Printer className="size-4" />} onClick={() => window.print()}>
              Print or save as PDF
            </Button>
          </div>
        )}
      </div>

      <article className="sheet print-sheet mx-auto max-w-[920px] px-6 py-8 sm:px-10">
        <header className="border-b border-rule pb-5">
          <p className="text-[14px] font-semibold text-ink-3">Acme Cloud Security, weekly sales report</p>
          <h1 className="mt-1 font-memo text-[38px] font-[580] leading-[1.04] tracking-[-0.018em] sm:text-[48px]">{data.period.label}</h1>
          <div className="mt-4 max-w-[64ch] space-y-2 font-memo text-[18.5px] leading-[1.6] text-ink-2">
            {data.headline.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        </header>

        <section className="grid grid-cols-2 gap-y-4 border-b border-rule py-5 sm:grid-cols-4">
          {[
            ["New leads", count(data.leads.new_this_week)],
            ["Drafts waiting", count(data.pending_drafts.length)],
            ["Approval rate", r.approval_rate === null ? "n/a" : pct(r.approval_rate)],
            ["Open pipeline", moneyK(data.pipeline.open_value)],
          ].map(([label, value]) => (
            <div key={label}>
              <div className="text-[13px] font-semibold text-ink-3">{label}</div>
              <div className="num text-[26px] font-bold">{value}</div>
            </div>
          ))}
        </section>

        <section className="break-inside-avoid border-b border-rule py-5">
          <h2 className="mb-3 font-memo text-[24px] font-[620] tracking-[-0.01em]">Top priorities</h2>
          {data.leads.top.length === 0 && data.pipeline.top_accounts.length === 0 ? (
            <p className="text-[14px] text-ink-3">Run the agent to fill this report.</p>
          ) : (
            <ol className="space-y-3 text-[14.5px]">
              {data.leads.top.map((l) => (
                <li key={`l${l.id}`} className="grid grid-cols-[44px_1fr] gap-3">
                  <span className="num text-[20px] font-bold">{l.score}</span>
                  <div>
                    <span className="font-semibold">{l.company}</span> <span className="text-ink-3">(new lead)</span>
                    <div className="text-ink-2">{l.reason}</div>
                    <a href={l.source_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1 text-[13px]">
                      {hostOf(l.source_url)} <ExternalLink className="size-3" aria-hidden />
                    </a>
                  </div>
                </li>
              ))}
              {data.pipeline.top_accounts.map((a) => (
                <li key={`a${a.id}`} className="grid grid-cols-[44px_1fr] gap-3">
                  <span className="num text-[20px] font-bold">{a.score}</span>
                  <div>
                    <span className="font-semibold">{a.company}</span>{" "}
                    <span className="text-ink-3">
                      (CRM, {a.stage}, {moneyK(a.value)}, {a.owner})
                    </span>
                    <div className="text-ink-2">{Object.values(a.why).length > 0 ? Object.values(a.why).join(" ") : a.reason.split(". ").slice(1).join(". ")}</div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>

        <div className="grid gap-6 border-b border-rule py-5 md:grid-cols-3">
          <AccountList title="Stalled deals" rows={data.stalled} empty="No stalled deals." />
          <AccountList title="No contact for 30+ days" rows={data.no_contact} empty="Every account was contacted recently." />
          <AccountList title="Likely upsells" rows={data.upsell} empty="No upsell signals." />
        </div>

        <section className="break-inside-avoid border-b border-rule py-5">
          <h2 className="mb-3 font-memo text-[24px] font-[620] tracking-[-0.01em]">Drafts waiting for approval</h2>
          {data.pending_drafts.length === 0 ? (
            <p className="text-[14px] text-ink-3">The queue is empty.</p>
          ) : (
            <ul className="grid gap-x-6 gap-y-1.5 text-[14px] sm:grid-cols-2">
              {data.pending_drafts.map((d) => (
                <li key={d.id}>
                  <Link to={`/approvals?draft=${d.id}`} className="font-semibold hover:underline">
                    {d.company}
                  </Link>
                  <span className="text-ink-3">, {d.kind === "outreach" ? "first email" : `follow-up for ${shortDate(d.send_date)}`}</span>
                  <div className="truncate text-ink-2">{d.subject}</div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="break-inside-avoid pt-5 text-[14px] text-ink-2">
          <h2 className="mb-2 font-memo text-[24px] font-[620] tracking-[-0.01em] text-ink">Reviews and agent activity</h2>
          <p>
            This week the team approved {r.approved}, edited {r.edited}, rejected {r.rejected} and sent {r.sent} drafts. The agent ran {data.agent.runs} {data.agent.runs === 1 ? "time" : "times"}
            {data.agent.avg_duration_s !== null ? ` (average ${data.agent.avg_duration_s} s)` : ""}, made {count(data.agent.tool_calls)} tool calls and used{" "}
            {count(data.agent.tokens)} AI tokens (about ${data.agent.cost_usd.toFixed(2)}). Scores use ideal customer profile v{data.icp_version || "default"}.
          </p>
          {r.recent_rejection_reasons.length > 0 && (
            <p className="mt-2">
              Recent rejection reasons: {r.recent_rejection_reasons.map((x) => `"${x}"`).join(", ")}.
            </p>
          )}
        </section>
      </article>
    </div>
  );
}
