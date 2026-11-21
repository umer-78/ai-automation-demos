import clsx from "clsx";
import { ExternalLink } from "lucide-react";
import { motion } from "motion/react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AccountDrawer, LeadDrawer } from "../components/Drawers";
import { RunButton } from "../components/Layout";
import { QUADRANTS } from "../components/radarMeta";
import RunLog from "../components/RunLog";
import { ErrorNote, FlagChip, ScoreBar, ScoreLegend, Skeleton, StatusChip } from "../components/ui";
import type { Overview as OverviewData } from "../lib/api";
import { count, hostOf, moneyK, shortDate, SIGNAL_LABEL } from "../lib/format";
import { useApi, useOnDataChanged } from "../lib/hooks";
import { useRun } from "../lib/run";

const LeadRadar = lazy(() => import("../components/LeadRadar"));
const AgentFlow3D = lazy(() => import("../components/AgentFlow3D"));

const CORNER: Record<string, string> = {
  "top-right": "right-4 top-4 text-right",
  "top-left": "left-4 top-4",
  "bottom-left": "bottom-4 left-4",
  "bottom-right": "bottom-4 right-4 text-right",
};

function Ledger({ data }: { data: OverviewData }) {
  const c = data.counts;
  const cells = [
    { label: "Leads scored", value: count(c.leads), note: c.avg_lead_score ? `average ${c.avg_lead_score}` : "none yet" },
    { label: "Hot leads", value: count(c.hot_leads), note: "score 75 or more" },
    { label: "Waiting for you", value: count(c.pending_drafts), note: `${count(c.approved_drafts)} approved, ${count(c.sent_drafts)} sent`, to: "/approvals" },
    { label: "Stalled deals", value: count(c.stalled), note: c.crm_analysed ? "same stage too long" : "checked on the first run", to: "/accounts?flag=stalled" },
    { label: "No contact 30+ days", value: count(c.no_contact), note: c.crm_analysed ? `of ${c.accounts} CRM accounts` : "checked on the first run", to: "/accounts?flag=no_contact" },
    { label: "Likely upsells", value: count(c.upsell), note: `open pipeline ${moneyK(c.open_pipeline)}`, to: "/accounts?flag=upsell" },
  ];
  return (
    <div className="panel grid grid-cols-2 divide-rule-soft overflow-hidden sm:grid-cols-3 lg:grid-cols-6 lg:divide-x">
      {cells.map((cell) => {
        const body = (
          <>
            <div className="text-[13px] font-semibold text-ink-2">{cell.label}</div>
            <div className="num mt-1 text-[30px] font-bold leading-none">{cell.value}</div>
            <div className="mt-1.5 text-[12.5px] text-ink-3">{cell.note}</div>
          </>
        );
        return cell.to ? (
          <Link key={cell.label} to={cell.to} className="border-b border-rule-soft px-5 py-4 transition-colors hover:bg-spruce/[0.03] lg:border-b-0">
            {body}
          </Link>
        ) : (
          <div key={cell.label} className="border-b border-rule-soft px-5 py-4 lg:border-b-0">
            {body}
          </div>
        );
      })}
    </div>
  );
}

export default function Overview() {
  const { data, error, reload } = useApi<OverviewData>("/api/overview");
  const { run, busy, error: runError, watch } = useRun();
  const [lead, setLead] = useState<number | null>(null);
  const [account, setAccount] = useState<number | null>(null);
  useOnDataChanged(useCallback(() => void reload(), [reload]));

  // pick up a run that is already going (e.g. started from another tab or by the scheduler)
  useEffect(() => {
    if (data?.running) watch(data.running);
  }, [data?.running, watch]);
  // while a run is going, refresh the radar every few seconds so beacons appear as leads are saved
  useEffect(() => {
    if (!busy) return;
    const id = window.setInterval(() => void reload(), 2500);
    return () => window.clearInterval(id);
  }, [busy, reload]);

  const shownRun = run ?? data?.latest_run ?? null;
  const integ = data?.integrations;

  return (
    <div className="space-y-8">
      <section className="grid items-stretch gap-6 lg:grid-cols-[1fr_1.08fr]">
        <div className="flex flex-col justify-center py-2">
          <motion.h1
            className="display text-[42px] sm:text-[54px] xl:text-[64px]"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: [0.2, 0.7, 0.2, 1] }}
          >
            Who to call this week, and what to say.
          </motion.h1>
          <p className="mt-5 max-w-[34rem] text-[17px] text-ink-2">
            One click and the agent reads Acme's product and deal notes, researches real companies, checks all {data?.counts.accounts ?? 50} CRM
            accounts, scores everything from 0 to 100 and writes the emails. You approve every message. The app itself cannot send email.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <RunButton size="lg" />
            {data && data.counts.pending_drafts > 0 && (
              <Link to="/approvals" className="inline-flex h-12 items-center rounded-lg border border-rule bg-sheet px-5 text-[15px] font-semibold hover:border-ink-3/50">
                Review {data.counts.pending_drafts} drafts
              </Link>
            )}
          </div>
          {runError && <p className="mt-3 text-[14px] text-crimson">{runError}</p>}
          {integ && (
            <dl className="mt-7 grid max-w-[34rem] grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13.5px]">
              <dt className="text-ink-3">AI</dt>
              <dd>{integ.ai}</dd>
              <dt className="text-ink-3">Research</dt>
              <dd>{integ.research}</dd>
              <dt className="text-ink-3">Sending</dt>
              <dd>{integ.sending}</dd>
            </dl>
          )}
        </div>
        <div className="console relative min-h-[380px] overflow-hidden sm:min-h-[460px]">
          <Suspense fallback={<div className="absolute inset-0 grid place-items-center text-[14px] text-sage">Loading radar</div>}>
            <LeadRadar leads={data?.radar ?? []} scanning={busy} onSelect={setLead} selectedId={lead} />
          </Suspense>
          {QUADRANTS.map((q) => (
            <span key={q.key} className={clsx("pointer-events-none absolute text-[12.5px] font-semibold text-sage", CORNER[q.corner])}>
              {q.label}
            </span>
          ))}
          <div className="pointer-events-none absolute bottom-11 left-1/2 w-[min(88%,36rem)] -translate-x-1/2 text-balance text-center text-[13px] text-[#cfe0d8]">
            {data?.radar.length ? (
              <>Closer to the centre and taller means a higher score. {data.radar.length} companies on the radar.</>
            ) : busy ? (
              "Researching companies"
            ) : (
              "Run the agent to fill the radar with real companies."
            )}
          </div>
        </div>
      </section>

      {error && <ErrorNote message={error} />}
      {data ? <Ledger data={data} /> : <Skeleton className="h-28 w-full" />}
      <Suspense fallback={<Skeleton className="h-[436px] w-full" />}>
        <AgentFlow3D run={shownRun} counts={data?.counts} />
      </Suspense>
      {shownRun && <RunLog run={shownRun} compact />}

      <div className="grid gap-6 lg:grid-cols-[1.25fr_1fr]">
        <section className="panel">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule-soft px-5 py-3.5">
            <h2 className="heading text-[16px]">Top leads from research</h2>
            <ScoreLegend />
          </header>
          {data && data.top_leads.length === 0 && <p className="px-5 py-8 text-[14px] text-ink-3">No leads yet. Run the agent to research the market.</p>}
          <ul className="divide-y divide-rule-soft">
            {(data?.top_leads ?? []).map((l) => (
              <li key={l.id}>
                <button onClick={() => setLead(l.id)} className="grid w-full gap-2 px-5 py-3.5 text-left transition-colors hover:bg-spruce/[0.03] sm:grid-cols-[1fr_220px] sm:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="heading text-[15.5px]">{l.company}</span>
                      <StatusChip status={l.status} />
                    </div>
                    <p className="mt-0.5 line-clamp-1 text-[14px] text-ink-2">
                      {l.signal ? `${SIGNAL_LABEL[l.signal] ?? l.signal}, ${shortDate(l.fact_date)}: ` : ""}
                      {l.fact}
                    </p>
                    <span className="mt-0.5 inline-flex items-center gap-1 text-[12.5px] text-ink-3">
                      Source {hostOf(l.source_url)} <ExternalLink className="size-3" aria-hidden />
                    </span>
                  </div>
                  <ScoreBar parts={l.parts} score={l.score} />
                </button>
              </li>
            ))}
          </ul>
          {data && data.top_leads.length > 0 && (
            <Link to="/leads" className="block border-t border-rule-soft px-5 py-2.5 text-[13.5px] font-semibold text-ink-2 hover:text-ink">
              See all {data.counts.leads} leads
            </Link>
          )}
        </section>

        <section className="panel">
          <header className="border-b border-rule-soft px-5 py-3.5">
            <h2 className="heading text-[16px]">CRM accounts that need attention</h2>
          </header>
          {data && !data.counts.crm_analysed && <p className="px-5 py-8 text-[14px] text-ink-3">The agent analyses the CRM on every run: stalled deals, accounts with no contact for 30+ days and likely upsells.</p>}
          <ul className="divide-y divide-rule-soft">
            {(data?.top_accounts ?? []).map((a) => (
              <li key={a.id}>
                <button onClick={() => setAccount(a.id)} className="w-full px-5 py-3.5 text-left transition-colors hover:bg-spruce/[0.03]">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="heading text-[15.5px]">{a.company}</span>
                    {a.flags.map((f) => (
                      <FlagChip key={f} flag={f} />
                    ))}
                    <span className="num ml-auto text-[14px] font-bold">{a.score}</span>
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-[14px] text-ink-2">{a.why}</p>
                  <p className="mt-0.5 text-[12.5px] text-ink-3">
                    {a.stage}, {moneyK(a.value)}, owner {a.owner}
                  </p>
                </button>
              </li>
            ))}
          </ul>
          {data?.counts.crm_analysed && (
            <Link to="/accounts" className="block border-t border-rule-soft px-5 py-2.5 text-[13.5px] font-semibold text-ink-2 hover:text-ink">
              See all {data.counts.accounts} accounts
            </Link>
          )}
        </section>
      </div>

      <LeadDrawer id={lead} onClose={() => setLead(null)} />
      <AccountDrawer id={account} onClose={() => setAccount(null)} />
    </div>
  );
}
