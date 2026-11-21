import { ExternalLink } from "lucide-react";
import { motion } from "motion/react";
import { useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { AccountDrawer, LeadDrawer } from "../components/Drawers";
import { RunButton } from "../components/Layout";
import RunLog from "../components/RunLog";
import { ErrorNote, FlagChip, ScoreBar, ScoreLegend, Skeleton, StatusChip } from "../components/ui";
import type { Overview as OverviewData } from "../lib/api";
import { count, hostOf, moneyK, shortDate, SIGNAL_LABEL } from "../lib/format";
import { useApi, useDataStatus, useOnDataChanged } from "../lib/hooks";
import { useRun } from "../lib/run";
import { Card, CardTitle, Section, btn } from "../world/Section";
import { world, useWorld } from "../world/store";

function Ledger({ data }: { data: OverviewData }) {
  const c = data.counts;
  const cells = [
    { label: "Leads scored", value: count(c.leads), note: c.avg_lead_score ? `average ${c.avg_lead_score}` : "none yet", to: "/leads" },
    { label: "Hot leads", value: count(c.hot_leads), note: "score 75 or more", to: "/leads" },
    { label: "Waiting for you", value: count(c.pending_drafts), note: `${count(c.approved_drafts)} approved, ${count(c.sent_drafts)} sent`, to: "/approvals" },
    { label: "Stalled deals", value: count(c.stalled), note: c.crm_analysed ? "same stage too long" : "checked on the first run", to: "/accounts?flag=stalled" },
    { label: "No contact 30+ days", value: count(c.no_contact), note: c.crm_analysed ? `of ${c.accounts} accounts` : "checked on the first run", to: "/accounts?flag=no_contact" },
    { label: "Likely upsells", value: count(c.upsell), note: `open pipeline ${moneyK(c.open_pipeline)}`, to: "/accounts?flag=upsell" },
  ];
  return (
    <div className="mt-7 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
      {cells.map((cell) => (
        <Link key={cell.label} to={cell.to} className="group">
          <div className="text-[13px] text-ink-3">{cell.label}</div>
          <div className="num mt-0.5 text-[28px] font-semibold leading-none tracking-[-0.02em] group-hover:underline">{cell.value}</div>
          <div className="mt-1 text-[12.5px] text-ink-3">{cell.note}</div>
        </Link>
      ))}
    </div>
  );
}

export default function Overview() {
  const { data, error, reload } = useApi<OverviewData>("/api/overview");
  const { run, busy, error: runError, watch } = useRun();
  const status = useDataStatus();
  const lead = useWorld((s) => s.lead);
  const account = useWorld((s) => s.account);
  useOnDataChanged(useCallback(() => void reload(), [reload]));

  // pick up a run that is already going (started from another tab or by the scheduler)
  useEffect(() => {
    if (data?.running) watch(data.running);
  }, [data?.running, watch]);
  // while a run is going, refresh so pins rise on the radar as leads are saved
  useEffect(() => {
    if (!busy) return;
    const id = window.setInterval(() => void reload(), 2500);
    return () => window.clearInterval(id);
  }, [busy, reload]);

  const shownRun = run ?? data?.latest_run ?? null;
  const integ = data?.integrations;
  const real = status?.mode === "real";

  return (
    <>
      <Section shot="home">
        <motion.h1 className="display text-[44px] sm:text-[56px] xl:text-[64px]" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: [0.2, 0.7, 0.2, 1] }}>
          Who to call this week, and what to say.
        </motion.h1>
        <p className="mt-5 max-w-[34rem] text-[17px] leading-relaxed text-ink-2">
          One click and the agent reads {real ? "your" : "Acme's"} product and deal notes, researches real companies, checks all {data?.counts.accounts ?? 50} CRM accounts, scores everything from 0 to 100 and writes the emails. You approve every message. The app itself cannot send email.
        </p>
        <div className="mt-7 flex flex-wrap items-center gap-3">
          <RunButton size="lg" />
          {data && data.counts.pending_drafts > 0 && (
            <Link to="/approvals" className={btn.secondary}>
              Review {data.counts.pending_drafts} drafts
            </Link>
          )}
        </div>
        {runError && <p className="mt-3 max-w-[34rem] text-[14px] text-crimson">{runError}</p>}
        {error && <ErrorNote message={error} />}
        {data ? <Ledger data={data} /> : <Skeleton className="mt-7 h-36 w-full" />}
        {integ && (
          <dl className="mt-6 grid max-w-[34rem] grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13.5px]">
            <dt className="text-ink-3">AI</dt>
            <dd>{integ.ai}</dd>
            <dt className="text-ink-3">Research</dt>
            <dd>{integ.research}</dd>
            <dt className="text-ink-3">Sending</dt>
            <dd>{integ.sending}</dd>
          </dl>
        )}
        <p className="mt-8 text-[13.5px] text-ink-3">Each pin on the radar is a real company. Closer to the centre and taller means a higher score. Scroll to follow the agent's day.</p>
      </Section>

      <Section shot="agent" wide>
        <Card>
          <CardTitle aside={shownRun ? `${shownRun.mode === "live" ? "live AI" : "offline planner"}, ${shownRun.tool_call_count} tool calls` : null}>How the agent works</CardTitle>
          <p className="text-[15px] leading-relaxed text-ink-2">
            Seven stations, one run: read the notes, research, score, check the CRM, write the first emails, plan the follow-ups and sum up. Every email stops at the gate for you. The bead on the track shows where the run is; a red light is a tool call the guardrails refused.
          </p>
          {shownRun ? <div className="mt-4"><RunLog run={shownRun} compact /></div> : <p className="mt-4 text-[14px] text-ink-3">No runs yet. Press Run agent.</p>}
        </Card>
      </Section>

      <Section shot="leads" side="right" wide>
        <Card>
          <CardTitle aside={<ScoreLegend />}>Top leads from research</CardTitle>
          {data && data.top_leads.length === 0 && <p className="text-[14px] text-ink-3">No leads yet. Run the agent to research the market.</p>}
          <ul className="-mx-2 divide-y divide-rule-soft">
            {(data?.top_leads ?? []).map((l) => (
              <li key={l.id}>
                <button
                  onClick={() => world.set({ lead: l.id })}
                  onMouseEnter={() => world.set({ hoverLead: l.id })}
                  onMouseLeave={() => world.set({ hoverLead: null })}
                  className="grid w-full gap-2 rounded-xl px-2 py-3 text-left transition-colors hover:bg-black/[0.03] sm:grid-cols-[1fr_180px] sm:items-center"
                >
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
            <Link to="/leads" className="mt-3 inline-block text-[14px] font-medium hover:underline">
              See all {data.counts.leads} leads
            </Link>
          )}
        </Card>
      </Section>

      <Section shot="crm" wide>
        <Card>
          <CardTitle aside={data?.counts.crm_analysed ? `${data.counts.accounts} accounts` : null}>CRM accounts that need attention</CardTitle>
          {data && !data.counts.crm_analysed && <p className="text-[14px] text-ink-3">The agent checks the CRM on every run: stalled deals, accounts with no contact for 30+ days and likely upsells.</p>}
          <p className="text-[13.5px] text-ink-3">Each pillar is an account, as tall as its deal or contract value. The ring on top is the flag: red stalled, amber no contact, teal likely upsell.</p>
          <ul className="-mx-2 mt-2 divide-y divide-rule-soft">
            {(data?.top_accounts ?? []).map((a) => (
              <li key={a.id}>
                <button
                  onClick={() => world.set({ account: a.id })}
                  onMouseEnter={() => world.set({ hoverAccount: a.id })}
                  onMouseLeave={() => world.set({ hoverAccount: null })}
                  className="w-full rounded-xl px-2 py-3 text-left transition-colors hover:bg-black/[0.03]"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="heading text-[15.5px]">{a.company}</span>
                    {a.flags.map((f) => (
                      <FlagChip key={f} flag={f} />
                    ))}
                    <span className="num ml-auto text-[14px] font-semibold">{a.score}</span>
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
            <Link to="/accounts" className="mt-3 inline-block text-[14px] font-medium hover:underline">
              See all {data.counts.accounts} accounts
            </Link>
          )}
        </Card>
      </Section>

      <Section shot="queue" side="right">
        <Card>
          <CardTitle>Your approval</CardTitle>
          <p className="text-[15px] leading-relaxed text-ink-2">
            Every email the agent writes waits in the first tray. Approve it, edit it or reject it with a reason; the reasons become rules for the next run. Approved emails are exported and sent by you, from your own inbox.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Link to="/approvals" className={btn.primary}>
              Open the queue{data ? ` (${data.counts.pending_drafts} waiting)` : ""}
            </Link>
            <Link to="/learning" className={btn.secondary}>
              See what it learned
            </Link>
          </div>
        </Card>
      </Section>

      <LeadDrawer id={lead} onClose={() => world.set({ lead: null })} />
      <AccountDrawer id={account} onClose={() => world.set({ account: null })} />
    </>
  );
}
