import clsx from "clsx";
import { Hash, Mail } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import BlurText from "../components/BlurText";
import OnboardingDrawer from "../components/OnboardingDrawer";
import { SERVICE_BRANCH } from "../components/flowNodes";
import { AnimatedNumber, Skeleton, useToast } from "../components/ui";
import { api, type Alert, type ChannelRow, type Cube, type LogRow, type Notification, type Overview as OverviewData, type TrendPoint } from "../lib/api";
import { count, money, shortDate, signedPct, slackText, timeAgo, workflowName } from "../lib/format";
import { useStatus } from "../lib/hooks";
import { dataChanged, useApi, useOnDataChanged } from "../lib/hooks";
import { Card, CardTitle, Section, btn } from "../world/Section";
import { sendRun, world, type Shot } from "../world/store";
import { barX, rowZ, sortedRows } from "../world/layout";

function Delta({ value, goodWhenDown = false, neutral = false }: { value: number | null; goodWhenDown?: boolean; neutral?: boolean }) {
  if (value === null) return null;
  const good = goodWhenDown ? value < 0 : value > 0;
  return <span className={clsx("num text-[13px] font-medium", neutral ? "text-[#5B616B]" : good ? "text-[#12805C]" : "text-[#B42318]")}>{signedPct(value)}</span>;
}

const LEGEND = [
  { color: "#0f9f88", label: "Cheaper than usual" },
  { color: "#f4f4f5", label: "Normal", ring: true },
  { color: "#f59e0b", label: "Watch" },
  { color: "#e5484d", label: "Alert" },
];

export default function Overview() {
  const toast = useToast();
  const status = useStatus();
  const real = status?.data.mode === "real";
  const [adding, setAdding] = useState(false);
  const [failing, setFailing] = useState(false);
  const overview = useApi<OverviewData>("/api/metrics/overview?days=30", 30000);
  const trend = useApi<{ series: TrendPoint[] }>("/api/metrics/trend?days=30");
  const channels = useApi<{ channels: ChannelRow[] }>("/api/metrics/channels?days=30");
  const alerts = useApi<{ alerts: Alert[] }>("/api/metrics/alerts");
  const cube = useApi<Cube>("/api/metrics/cube?days=30&by=client", 60000);
  const logs = useApi<LogRow[]>("/api/automation/logs?limit=6", 8000);
  const feed = useApi<Notification[]>("/api/notifications?limit=4", 8000);
  const reloads = [overview.reload, alerts.reload, logs.reload, feed.reload];
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const refresh = useCallback(() => reloads.forEach((r) => void r()), reloads);
  useOnDataChanged(refresh);

  async function forceFailure() {
    setFailing(true);
    try {
      const r = await api.post<{ status: string; run_id: string }>("/api/demo/forced-failure");
      sendRun(false, ["ads"]);
      world.set({ step: "errors" });
      toast("failure", `Forced failure logged (run ${r.run_id}) and the Slack alert was sent.`);
      dataChanged();
    } catch (e) {
      toast("failure", e instanceof Error ? e.message : String(e));
    } finally {
      setFailing(false);
    }
  }

  /** The camera goes to the flagged client's row, on the days of the flagged week. */
  const alertFocus = useMemo<Shot | null>(() => {
    const a = alerts.data?.alerts[0];
    const c = cube.data;
    if (!a || !c) return null;
    const ri = sortedRows(c).findIndex((r) => r.client_id === a.client_id);
    if (ri < 0) return null;
    const days = c.dates.flatMap((d, i) => (d >= a.week.start && d <= a.week.end ? [i] : []));
    const mid = days.length ? days.reduce((x, y) => x + y, 0) / days.length : c.dates.length - 4;
    const x = barX(mid);
    const z = rowZ(ri);
    return { pos: [x + 4.2, 6.4, z + 8.6], target: [x - 1.2, 1, z - 1.2], shift: -0.17, zone: "spend" };
  }, [alerts.data, cube.data]);
  const o = overview.data;
  const series = trend.data?.series ?? [];
  const spends = series.map((p) => p.spend);
  const low = spends.length ? Math.min(...spends) : null;
  const high = spends.length ? Math.max(...spends) : null;
  const avg = spends.length ? spends.reduce((a, b) => a + b, 0) / spends.length : null;

  return (
    <>
      <Section shot="home" wide>
        <BlurText text="From new client row to first report, untouched." className="text-[clamp(44px,5.4vw,78px)] font-semibold leading-[0.98] tracking-[-0.045em]" />
        <p className="mt-5 max-w-[46ch] text-[17px] leading-relaxed text-[#3f444c]">
          Add a client and the hub routes them by service, writes their brief and starts daily reporting. Every run is logged, and failures ping Slack. The model behind this text is that automation, running live.
        </p>
        <dl className="mt-8 flex flex-wrap gap-x-10 gap-y-4">
          {[
            { label: "Ad spend, 30 days", value: o?.totals.spend, fmt: (n: number) => money(n), delta: <Delta value={o?.totals.change.spend ?? null} neutral /> },
            { label: "Conversions", value: o?.totals.conversions, fmt: (n: number) => count(n), delta: <Delta value={o?.totals.change.conversions ?? null} /> },
            { label: "Cost per conversion", value: o?.totals.cpa ?? undefined, fmt: (n: number) => money(n, true), delta: <Delta value={o?.totals.change.cpa ?? null} goodWhenDown /> },
          ].map((k) => (
            <div key={k.label}>
              <dt className="text-[13.5px] text-[#5B616B]">{k.label}</dt>
              <dd className="mt-1 flex items-baseline gap-2">
                <span className="num text-[30px] font-semibold tracking-[-0.03em]">{k.value != null ? <AnimatedNumber value={k.value} format={k.fmt} /> : "…"}</span>
                {k.delta}
              </dd>
            </div>
          ))}
        </dl>
        <div className="mt-8 flex flex-wrap gap-3">
          <button type="button" className={btn.primary} onClick={() => setAdding(true)}>
            Add a client
          </button>
          <button type="button" className={btn.secondary} onClick={() => sendRun(true, ["seo", "ads", "web"])}>
            Send a test run
          </button>
          {!real && (
            <button type="button" className={clsx(btn.quiet, "text-[#B42318]")} onClick={forceFailure} disabled={failing}>
              {failing ? "Failing…" : "Force a failure"}
            </button>
          )}
        </div>
        <p className="mt-10 flex items-center gap-3 text-[13.5px] text-[#5B616B]">
          <span aria-hidden="true" className="scroll-cue" />
          Scroll to fly through the last 30 days
        </p>
      </Section>

      <Section shot="metrics">
        <Card>
          <CardTitle aside={o ? `${shortDate(o.period.start)} to ${shortDate(o.period.end)}` : undefined}>Last 30 days</CardTitle>
          <p className="text-[15px] leading-relaxed text-[#3f444c]">
            Each pillar is one client on one day: height is spend, colour is cost per conversion against that client's usual. Hover any pillar for its numbers.
          </p>
          <div className="mt-5 grid grid-cols-3 gap-3">
            {[
              ["Lowest day", low],
              ["Average", avg],
              ["Highest day", high],
            ].map(([label, v]) => (
              <div key={label as string} className="rounded-xl bg-black/[0.035] px-3.5 py-3">
                <div className="text-[12.5px] text-[#5B616B]">{label}</div>
                <div className="num mt-0.5 text-[19px] font-semibold tracking-tight">{v != null ? money(v as number) : "…"}</div>
              </div>
            ))}
          </div>
          <ul className="mt-5 flex flex-wrap gap-x-4 gap-y-2 text-[13px] text-[#3f444c]">
            {LEGEND.map((l) => (
              <li key={l.label} className="flex items-center gap-1.5">
                <span aria-hidden="true" className={clsx("inline-block size-2.5 rounded-[3px]", l.ring && "ring-1 ring-black/20")} style={{ background: l.color }} />
                {l.label}
              </li>
            ))}
          </ul>
        </Card>
      </Section>

      <Section shot="alert" side="right" focus={alertFocus}>
        {!alerts.data ? (
          <Skeleton className="h-40 rounded-[22px]" />
        ) : alerts.data.alerts.length ? (
          <Card tone="alert">
            <p className="flex items-center gap-2 text-[14px] font-semibold text-[#B42318]">
              <span aria-hidden="true" className="inline-block size-2 rounded-full bg-[#D92D20]" />
              Needs attention
            </p>
            <ul className="mt-3 space-y-5">
              {alerts.data.alerts.slice(0, 3).map((a) => (
                <li key={`${a.client_id}-${a.channel}`}>
                  <h2 className="text-[24px] font-semibold leading-tight tracking-[-0.025em]">{a.client}</h2>
                  <p className="mt-1.5 text-[15.5px] leading-relaxed text-[#2B2F36]">
                    {a.channel} cost per conversion rose {a.change != null ? `${Math.round(a.change * 100)}%` : ""} this week, from {money(a.cpa_last_week, true)} to {money(a.cpa_this_week, true)}. Conversions went from{" "}
                    {count(a.conversions_last_week)} to {count(a.conversions_this_week)}.
                  </p>
                  <Link to={`/reporting?client=${a.client_id}`} className={clsx(btn.primary, "mt-4")}>
                    Open the report
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        ) : (
          <Card>
            <CardTitle>Nothing needs attention</CardTitle>
            <p className="text-[15px] text-[#3f444c]">No campaign's cost per conversion rose more than 25% week on week.</p>
          </Card>
        )}
      </Section>

      <Section shot="channels">
        <Card>
          <CardTitle aside="share of spend">Where the money went</CardTitle>
          {!channels.data ? (
            <Skeleton className="h-40" />
          ) : (
            <ul className="divide-y divide-black/[0.07]">
              {channels.data.channels.map((c) => (
                <li key={c.channel} className="py-3.5">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="font-medium">{c.channel}</span>
                    <span className="num font-semibold">{Math.round(c.share_of_spend * 100)}%</span>
                  </div>
                  <div className="num mt-0.5 flex justify-between gap-3 text-[13.5px] text-[#5B616B]">
                    <span>
                      {money(c.spend)}, {count(c.conversions)} conversions
                    </span>
                    <span>{money(c.cpa, true)} each</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </Section>

      <Section shot="runs" side="right">
        <Card>
          <CardTitle aside={<Link to="/automations" className="font-medium text-black hover:underline">All runs</Link>}>Latest runs</CardTitle>
          {!logs.data ? (
            <Skeleton className="h-40" />
          ) : (
            <ul className="divide-y divide-black/[0.07]">
              <AnimatePresence initial={false}>
                {logs.data.slice(0, 5).map((l) => (
                  <motion.li
                    key={l.id}
                    layout
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.9 }}
                    transition={{ type: "spring", stiffness: 350, damping: 40 }}
                    className="flex items-center justify-between gap-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 truncate font-medium">
                        <span aria-hidden="true" className={clsx("inline-block size-2 shrink-0 rounded-full", l.status === "success" ? "bg-[#0f9f88]" : "bg-[#e5484d]")} />
                        {workflowName[l.workflow] ?? l.workflow}
                      </div>
                      <div className="truncate pl-4 text-[12.5px] text-[#5B616B]">{l.error ?? `${l.source} run, ${l.duration_ms ?? 0} ms`}</div>
                    </div>
                    <span className="shrink-0 text-[12.5px] text-[#5B616B]">{timeAgo(l.created_at)}</span>
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          )}
          <h3 className="mt-6 text-[15px] font-semibold">Slack and email</h3>
          <ul className="mt-2 space-y-2.5">
            {(feed.data ?? []).map((n) => (
              <li key={n.id} className="flex gap-2.5 text-[13.5px]">
                <span className={clsx("mt-0.5 grid size-6 shrink-0 place-items-center rounded-md", n.kind === "alert" ? "bg-[#fef3f2] text-[#B42318]" : "bg-black/[0.05] text-[#5B616B]")}>
                  {n.channel === "email" ? <Mail className="size-3.5" /> : <Hash className="size-3.5" />}
                </span>
                <p className="line-clamp-2 min-w-0">{slackText(n.subject ?? n.body)}</p>
              </li>
            ))}
          </ul>
        </Card>
      </Section>

      <Section shot="settings">
        <Card>
          <CardTitle>{real ? "Your accounts" : "Go live with your own accounts"}</CardTitle>
          <p className="text-[15px] leading-relaxed text-[#3f444c]">
            {real
              ? `Every figure on this site comes from ${status?.data.live_sources.length ? status.data.live_sources.join(", ") : "the files you imported"}. Link more accounts or import more history in Settings. Lit sockets on the board are live.`
              : "The five clients here are samples whose numbers follow published 2026 industry medians. Import a Google Ads or Meta Ads export, or connect the accounts themselves in Settings, and every screen switches to your real numbers. Lit sockets on the board are live."}
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link to="/settings" className={btn.primary}>
              Add API keys
            </Link>
            <Link to="/clients" className={btn.secondary}>
              See clients
            </Link>
          </div>
        </Card>
      </Section>

      <OnboardingDrawer open={adding} onClose={() => setAdding(false)} onFinished={(ok, services) => sendRun(ok, services.map((x) => SERVICE_BRANCH[x]).filter(Boolean))} />
    </>
  );
}
