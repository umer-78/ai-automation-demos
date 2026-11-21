import clsx from "clsx";
import { Download, RefreshCw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Empty, ErrorNote, Segmented, Skeleton, useToast } from "../components/ui";
import { Card, CardTitle, Section } from "../world/Section";
import { world } from "../world/store";
import { api, type Alert, type ChannelRow, type Insights, type Overview, type PipelineResult, type Summary, type TrendPoint } from "../lib/api";
import { count, money, pct, shortDate, signedPct } from "../lib/format";
import { dataChanged, useApi, useOnDataChanged, useStatus } from "../lib/hooks";

type Benchmarks = {
  sources: { id: string; publisher: string; title: string; url: string; used_for: string }[];
  organic_ctr: number;
  clients: { client: string; industry: string | null; category: string; google: { ctr: number; cpc: number; cpl: number }; meta: { ctr: number; cvr: number; cpl: number }; organic_cvr: number }[];
};

/** Where every number on this page comes from: published medians in the demo, your accounts in real mode. */
function SourcesPanel() {
  const status = useStatus();
  const bench = useApi<Benchmarks>("/api/data/benchmarks");
  const data = status?.data;
  if (!data) return <Skeleton className="h-48" />;
  if (data.mode === "real") {
    return (
      <Card>
        <CardTitle>Where these numbers come from</CardTitle>
        <p className="text-[15px] leading-relaxed text-[#3f444c]">
          {data.live_sources.length ? `Pulled from ${data.live_sources.join(", ")} through their reporting APIs` : "Loaded from the files you imported"}, stored as one row per client, channel and day, and added up when this page opens. Nothing is estimated or filled in: a day an account did not report has no row.
          {data.last_sync ? ` Last sync ${shortDate(data.last_sync.at)}.` : ""}
        </p>
      </Card>
    );
  }
  const b = bench.data;
  return (
    <Card>
      <CardTitle>Where these numbers come from</CardTitle>
      <p className="text-[15px] leading-relaxed text-[#3f444c]">
        The clients are invented. Their numbers are not: each one follows the published 2026 median for its industry, with a fixed offset of up to 12% per client and normal day-to-day noise. GreenLeaf's Meta Ads cost per lead is pushed up for the last week so the alert has something real to catch.
      </p>
      {!b ? (
        <Skeleton className="mt-4 h-40" />
      ) : (
        <>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-[13.5px]">
              <thead className="text-[12.5px] text-[#5B616B]">
                <tr>
                  <th className="py-1.5 pr-3 font-medium">Client</th>
                  <th className="py-1.5 pr-3 font-medium">Benchmark industry</th>
                  <th className="num py-1.5 pr-3 text-right font-medium">Google CPC</th>
                  <th className="num py-1.5 pr-3 text-right font-medium">Google cost per lead</th>
                  <th className="num py-1.5 text-right font-medium">Meta cost per lead</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[0.06]">
                {b.clients.map((c) => (
                  <tr key={c.client}>
                    <td className="py-2 pr-3 font-medium">{c.client}</td>
                    <td className="py-2 pr-3 text-[#5B616B]">{c.category}</td>
                    <td className="num py-2 pr-3 text-right">{money(c.google.cpc, true)}</td>
                    <td className="num py-2 pr-3 text-right">{money(c.google.cpl, true)}</td>
                    <td className="num py-2 text-right">{money(c.meta.cpl, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="mt-4 space-y-2 text-[13.5px] text-[#3f444c]">
            {b.sources.map((src) => (
              <li key={src.id}>
                <a href={src.url} target="_blank" rel="noreferrer" className="font-medium text-black underline decoration-black/25 underline-offset-2 hover:decoration-black">
                  {src.publisher}, {src.title}
                </a>
                <span className="block text-[#5B616B]">{src.used_for}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

function ChangeCell({ value, goodWhenDown = false }: { value: number | null; goodWhenDown?: boolean }) {
  if (value === null) return <span className="text-slate">n/a</span>;
  const good = goodWhenDown ? value <= 0 : value >= 0;
  return <span className={clsx("num", good ? "text-aurora-ink" : "text-ember-ink")}>{signedPct(value)}</span>;
}

function PipelinePanel({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState<PipelineResult[]>([]);
  async function run() {
    setBusy(true);
    try {
      const r = await api.post<PipelineResult>("/api/jobs/daily-metrics");
      setRuns((prev) => [r, ...prev].slice(0, 3));
      toast("success", `Pipeline loaded ${r.fetched} rows: ${r.inserted} new, ${r.updated} updated.`);
      onDone();
      dataChanged();
    } catch (e) {
      toast("failure", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <CardTitle aside={<Button size="sm" busy={busy} icon={<RefreshCw className="size-3.5" />} onClick={run}>Run now</Button>}>Daily pipeline</CardTitle>
      <p className="text-[14px] text-slate">
        Runs every morning. It reloads the last 14 days (ad platforms restate late conversions) and upserts on client, date and channel, so running it twice never adds duplicate rows.
      </p>
      {runs.length > 0 && (
        <table className="num mt-4 w-full text-[13.5px]">
          <thead className="text-slate">
            <tr><th className="py-1 text-left font-medium">Run</th><th className="text-right font-medium">Fetched</th><th className="text-right font-medium">New</th><th className="text-right font-medium">Updated</th><th className="text-right font-medium">Rows in table</th></tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id} className="border-t border-edge">
                <td className="py-1.5">{r.run_id}</td>
                <td className="text-right">{count(r.fetched)}</td>
                <td className="text-right">{count(r.inserted)}</td>
                <td className="text-right">{count(r.updated)}</td>
                <td className="text-right font-semibold">{count(r.total_rows)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {runs.length > 1 && runs[0].total_rows === runs[1].total_rows && (
        <p className="mt-3 text-[13.5px] text-aurora-ink">Same row count after a rerun: no duplicates.</p>
      )}
    </Card>
  );
}

function SummaryPanel() {
  const toast = useToast();
  const latest = useApi<{ run_id: string | null; summaries: (Summary & { period_start?: string; period_end?: string })[] }>("/api/summaries/latest");
  const [fresh, setFresh] = useState<{ week: { start: string; end: string }; generated_by: string; summaries: Summary[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const clients = useApi<{ id: number; name: string }[]>("/api/clients");
  const names = useMemo(() => Object.fromEntries((clients.data ?? []).map((c) => [c.id, c.name])), [clients.data]);

  async function generate() {
    setBusy(true);
    try {
      const r = await api.post<{ week: { start: string; end: string }; generated_by: string; summaries: Summary[] }>("/api/summaries/weekly");
      setFresh(r);
      toast("success", `Weekly summary written for ${r.summaries.length} clients.`);
      dataChanged();
    } catch (e) {
      toast("failure", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const items: Summary[] = fresh?.summaries ?? (latest.data?.summaries ?? []).map((s) => ({ ...s, client: names[s.client_id] ?? `Client ${s.client_id}` }));
  const by = fresh?.generated_by ?? items[0]?.generated_by;
  return (
    <Card>
      <CardTitle aside={<Button size="sm" variant="primary" busy={busy} icon={<Sparkles className="size-3.5" />} onClick={generate}>Write this week's summary</Button>}>Weekly summary</CardTitle>
      {fresh && <p className="mb-4 text-[13px] text-slate">Week of {shortDate(fresh.week.start)} to {shortDate(fresh.week.end)}.</p>}
      {items.length === 0 ? (
        <Empty title="No summary yet">Three plain-English sentences per client, written from this week's numbers.</Empty>
      ) : (
        <div className="grid max-h-[40vh] gap-y-5 overflow-y-auto pr-1">
          {items.map((s) => (
            <article key={s.client_id}>
              <h3 className="font-semibold">{s.client}</h3>
              <p className="mt-1 text-[14.5px] leading-relaxed text-ink/85">{s.sentences.join(" ")}</p>
            </article>
          ))}
        </div>
      )}
      {by && <p className="mt-5 text-[12.5px] text-slate">{by === "ai" ? "Written by the AI model from the live numbers." : "Offline template. Add a Claude key in Settings for AI-written summaries."}</p>}
    </Card>
  );
}

function PacingBars({ data }: { data: Insights["pacing"] }) {
  return (
    <ul className="divide-y divide-black/[0.07]">
      {data.map((p) => (
        <li key={p.client_id} className="flex items-center justify-between gap-4 py-2.5 text-[14px]">
          <span className="min-w-0">
            <span className="block truncate font-medium">{p.client}</span>
            <span className="num block text-[12.5px] text-[#5B616B]">
              {money(p.spend_mtd)} of {money(p.monthly_budget)}, projected {money(p.projected_month)}
            </span>
          </span>
          <span
            className={clsx(
              "shrink-0 rounded-full px-2.5 py-1 text-[12.5px] font-medium",
              p.status === "over" ? "bg-[#fef3f2] text-[#B42318]" : p.status === "under" ? "bg-[#fff7e6] text-[#8a5a00]" : "bg-[#e7f6f2] text-[#0b5f52]",
            )}
          >
            {p.status === "on track" ? "On track" : p.status === "over" ? "Over pace" : "Under pace"}
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function Reporting() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const clientId = params.get("client") ? Number(params.get("client")) : null;
  const [days, setDays] = useState(30);
  const q = `days=${days}${clientId ? `&client_id=${clientId}` : ""}`;
  const overview = useApi<Overview>(`/api/metrics/overview?days=${days}`);
  const trend = useApi<{ series: TrendPoint[] }>(`/api/metrics/trend?${q}`);
  const channels = useApi<{ channels: ChannelRow[] }>(`/api/metrics/channels?${q}`);
  const alerts = useApi<{ alerts: Alert[]; threshold: number }>("/api/metrics/alerts");
  const insights = useApi<Insights>(`/api/metrics/insights${clientId ? `?client_id=${clientId}` : ""}`);
  const { reload: r1 } = overview;
  const { reload: r2 } = trend;
  const { reload: r3 } = channels;
  const { reload: r4 } = alerts;
  const { reload: r5 } = insights;
  const refresh = useCallback(() => {
    void r1(); void r2(); void r3(); void r4(); void r5();
  }, [r1, r2, r3, r4, r5]);
  useOnDataChanged(refresh);
  // the landscape, ribbon and ring in the world follow the client filter
  useEffect(() => world.set({ clientId }), [clientId]);
  useEffect(() => () => world.set({ clientId: null }), []);

  const clientName = overview.data?.clients.find((c) => c.client_id === clientId)?.client;
  const alertKeys = new Set((alerts.data?.alerts ?? []).map((a) => `${a.client_id}`));
  const series = trend.data?.series ?? [];
  const total = series.reduce((a, p) => a + p.spend, 0);
  const low = series.length ? Math.min(...series.map((p) => p.spend)) : null;
  const high = series.length ? Math.max(...series.map((p) => p.spend)) : null;

  return (
    <>
      <Section shot="reporting" wide>
        <Card>
          <CardTitle
            aside={
              <button type="button" onClick={() => void api.download(`/api/metrics/export.csv?days=${days}`, `northwind-metrics-${days}d.csv`).catch((e) => toast("failure", e instanceof Error ? e.message : String(e)))} className="inline-flex items-center gap-1.5 font-medium text-black hover:underline">
                <Download className="size-3.5" /> Export CSV
              </button>
            }
          >
            Reporting
          </CardTitle>
          <p className="text-[15px] leading-relaxed text-[#3f444c]">Loaded by the Python pipeline, one row per client, channel and day. Every figure here, and every pillar behind it, is calculated from those rows when you open the page.</p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <select aria-label="Client" className="field !w-auto min-w-[200px]" value={clientId ?? ""} onChange={(e) => setParams(e.target.value ? { client: e.target.value } : {})}>
              <option value="">All clients</option>
              {(overview.data?.clients ?? []).map((c) => <option key={c.client_id} value={c.client_id}>{c.client}</option>)}
            </select>
            <Segmented label="Period" value={days} onChange={setDays} options={[{ value: 7, label: "7 days" }, { value: 30, label: "30 days" }, { value: 60, label: "60 days" }]} />
          </div>
          {overview.error && <ErrorNote message={overview.error} />}
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[520px] text-[14px]">
              <thead>
                <tr className="text-left text-[12.5px] text-[#5B616B]">
                  <th className="pb-2 font-medium">Client</th>
                  <th className="pb-2 text-right font-medium">Spend</th>
                  <th className="pb-2 text-right font-medium">Conv.</th>
                  <th className="pb-2 text-right font-medium">Per conv.</th>
                  <th className="pb-2 text-right font-medium">Change</th>
                </tr>
              </thead>
              <tbody>
                {!overview.data && <tr><td colSpan={5}><Skeleton className="h-24" /></td></tr>}
                {overview.data?.clients.map((c) => (
                  <tr key={c.client_id} className={clsx("cursor-pointer border-t border-black/[0.07] hover:bg-black/[0.03]", clientId === c.client_id && "bg-black/[0.05]")} onClick={() => setParams(clientId === c.client_id ? {} : { client: String(c.client_id) })}>
                    <td className="py-2.5 font-medium">
                      <span className="inline-flex items-center gap-2">
                        {c.client}
                        {alertKeys.has(String(c.client_id)) && <span aria-label="Cost alert" className="inline-block size-1.5 rounded-full bg-[#e5484d]" />}
                      </span>
                    </td>
                    <td className="num py-2.5 text-right">{money(c.spend)}</td>
                    <td className="num py-2.5 text-right">{count(c.conversions)}</td>
                    <td className="num py-2.5 text-right">{money(c.cpa, true)}</td>
                    <td className="py-2.5 text-right"><ChangeCell value={c.change.cpa} goodWhenDown /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {alerts.data && alerts.data.alerts.length > 0 && (
            <p className="mt-4 rounded-xl bg-[#fef3f2] px-4 py-3 text-[13.5px] text-[#7a271a]">
              {alerts.data.alerts.map((a) => `${a.client}, ${a.channel}: cost per conversion ${money(a.cpa_last_week, true)} to ${money(a.cpa_this_week, true)} (${signedPct(a.change)}) this week.`).join(" ")}
            </p>
          )}
        </Card>
      </Section>

      <Section shot="channels">
        <Card>
          <CardTitle aside={clientName ?? "all clients"}>Channels</CardTitle>
          {!channels.data ? (
            <Skeleton className="h-40" />
          ) : (
            <ul className="divide-y divide-black/[0.07]">
              {channels.data.channels.map((c) => (
                <li key={c.channel} className="py-3">
                  <div className="flex justify-between gap-3">
                    <span className="font-medium">{c.channel}</span>
                    <span className="num font-semibold">{pct(c.share_of_spend)}</span>
                  </div>
                  <div className="num mt-0.5 flex justify-between gap-3 text-[13.5px] text-[#5B616B]">
                    <span>{money(c.spend)}, {count(c.conversions)} conversions, {pct(c.ctr, 1)} CTR</span>
                    <span>{money(c.cpa, true)} each</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </Section>

      <Section shot="metrics" side="right">
        <Card>
          <CardTitle aside={`${days} days${clientName ? `, ${clientName}` : ""}`}>Daily spend</CardTitle>
          <div className="grid grid-cols-3 gap-3">
            {[
              ["Total", total ? money(total) : "…"],
              ["Lowest day", low != null ? money(low) : "…"],
              ["Highest day", high != null ? money(high) : "…"],
            ].map(([label, v]) => (
              <div key={label} className="rounded-xl bg-black/[0.035] px-3.5 py-3">
                <div className="text-[12.5px] text-[#5B616B]">{label}</div>
                <div className="num mt-0.5 text-[18px] font-semibold tracking-tight">{v}</div>
              </div>
            ))}
          </div>
          {insights.data && (
            <p className="mt-4 text-[14px] text-[#3f444c]">
              Next 14 days, if the last 28 hold: <span className="num font-semibold text-black">{money(insights.data.forecast.projected_total ?? 0)}</span>, changing {money(insights.data.forecast.slope_per_day, true)} a day.
            </p>
          )}
        </Card>
      </Section>

      <Section shot="clients" wide>
        <Card>
          <CardTitle>Budget pacing, this month</CardTitle>
          {insights.data ? <PacingBars data={insights.data.pacing} /> : <Skeleton className="h-40" />}
          <h3 className="mt-6 text-[15px] font-semibold">Unusual days</h3>
          {!insights.data ? (
            <Skeleton className="mt-2 h-24" />
          ) : insights.data.anomalies.length === 0 ? (
            <p className="mt-1 text-[14px] text-[#5B616B]">Daily cost per conversion stayed within its normal range.</p>
          ) : (
            <ul className="mt-2 space-y-2 text-[14px]">
              {insights.data.anomalies.slice(0, 5).map((a) => (
                <li key={`${a.client_id}${a.channel}${a.date}`} className="flex justify-between gap-3">
                  <span>{shortDate(a.date)}: {a.client}, {a.channel}</span>
                  <span className="num shrink-0 text-[#B42318]">{money(a.cpa, true)} vs {money(a.baseline_cpa, true)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </Section>

      <Section shot="metrics" wide>
        <SummaryPanel />
      </Section>

      <Section shot="runs" side="right">
        <PipelinePanel onDone={refresh} />
      </Section>

      <Section shot="reporting" wide>
        <SourcesPanel />
      </Section>
    </>
  );
}
