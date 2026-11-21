import { useState, type FormEvent } from "react";
import { api, CHANNELS, money, num, pct, type ImportResult, type SampleBasis, type WeeklySummary } from "../api";
import { hub, useHub } from "../store";
import { refresh } from "../data";
import { NumberTicker } from "../components/NumberTicker";
import { DailyChart } from "../components/DailyChart";
import { day } from "../lib/format";
import { cn } from "../lib/cn";
import { Button, ErrorNote, Field, Note, Panel, Part, Section, Select, useAction } from "./kit";

const worst = (wow: Record<string, number | null>) => {
  const vals = Object.values(wow).filter((v): v is number => v != null);
  return vals.length ? vals.reduce((a, b) => (Math.abs(b) > Math.abs(a) ? b : a)) : null;
};

const usd2 = (v: number) => `$${v.toFixed(2)}`;

/** The sample clients are fictional; their cost per click and cost per lead are published benchmarks. */
function SampleBasisNote({ basis }: { basis: SampleBasis }) {
  return (
    <details className="skips">
      <summary>Where the sample numbers come from</summary>
      <ul>
        {basis.clients.map((c) => (
          <li key={c.client_id}>
            {c.client}, priced as {c.category}: Google Ads {usd2(c.google.cpc)} a click and {usd2(c.google.cpl)} a lead;
            Meta Ads {usd2(c.meta.cpc)} a click and {usd2(c.meta.cpl)} a lead{c.meta.note ? " (all-industry median)" : ""}.
          </li>
        ))}
        <li>
          Sources: <a className="link" href={basis.sources["Google Ads"].url} target="_blank" rel="noopener noreferrer">{basis.sources["Google Ads"].title}</a>;{" "}
          <a className="link" href={basis.sources["Meta Ads"].url} target="_blank" rel="noopener noreferrer">{basis.sources["Meta Ads"].title}</a>.
          Daily budgets are set per client and pace a little each day. SEO rows are illustrative, with no benchmark behind them.
        </li>
      </ul>
    </details>
  );
}

export function Reporting() {
  const dash = useHub((s) => s.dashboard);
  const focus = useHub((s) => s.focusClient);
  const act = useAction();
  const [jobNote, setJobNote] = useState<string | null>(null);
  const [weekly, setWeekly] = useState<WeeklySummary | null>(null);

  const runJob = async () => {
    const r = await act.run("job", () => api.runJob());
    if (!r) return;
    setJobNote(`Pulled ${num(r.upserted)} rows from the ${r.source} for ${r.span} and refreshed the report. ${
      r.duplicate_rows ? `${r.duplicate_rows} repeated rows were merged, not double counted.` : "No repeated rows."}`);
    hub.sendPackets([2, 3]);
    await refresh("dashboard", "log", "status");
  };
  const writeWeekly = async (fresh: boolean) => {
    const r = await act.run("weekly", () => api.weekly(fresh));
    if (!r) return;
    setWeekly(r);
    hub.sendPackets([2]);
    void refresh("log");
  };

  if (!dash) {
    return (
      <Section id="reporting" scene={2}>
        <Panel id="reporting" title="Ad performance, last 30 days" intro="Loading the report from the hub." busy>{null}</Panel>
      </Section>
    );
  }

  const k = dash.kpis;
  const totalSpend = dash.channels.reduce((a, c) => a + c.spend, 0) || 1;
  const alert = dash.alerts[0];

  return (
    <Section id="reporting" scene={2}>
      <Panel id="reporting" busy={act.busy !== null} title="Ad performance, last 30 days"
        intro={`Google Ads, Meta Ads and SEO for every active client, ${day(k.window[0])} to ${day(k.window[1])}. The daily job re-reads the last 14 days, so late conversions still land.`}>
        <dl className="kpis">
          <div><dt>Spend</dt><dd><NumberTicker value={k.spend} prefix="$" /></dd></div>
          <div><dt>Clicks</dt><dd><NumberTicker value={k.clicks} /></dd></div>
          <div><dt>Conversions</dt><dd><NumberTicker value={k.conversions} /></dd></div>
          <div><dt>Cost per conversion</dt><dd>{k.cpa == null ? "—" : <NumberTicker value={k.cpa} decimalPlaces={2} prefix="$" />}</dd></div>
        </dl>

        {alert && (
          <div className="alert" role="note">
            <p>
              <b>{alert.client}</b>: {alert.channel} cost per conversion is up {pct(alert.change_pct).replace("+", "")} on last week,
              from {money(alert.cpa_prev, 2)} to {money(alert.cpa_now, 2)}.
            </p>
            <p className="small mt-1">Alerts fire when it rises more than {dash.threshold_pct}% week over week.</p>
            <button type="button" className="link mt-2" onClick={() => hub.set({ focusClient: alert.client_id })}>Show it in the city</button>
          </div>
        )}

        <Part title="Day by day">
          <DailyChart title="Spend per day" color="#0F2A3F" format={(n) => money(n)}
            points={dash.trend.map((p) => ({ date: p.date, value: p.spend }))} />
          <DailyChart title="Conversions per day" color="#12968A" format={(n) => num(n)}
            points={dash.trend.map((p) => ({ date: p.date, value: p.conversions }))} />
        </Part>

        <Part title="By channel">
          <ul className="bars">
            {dash.channels.map((c) => (
              <li key={c.channel}>
                <span>{c.channel}</span>
                <span className="bar" aria-hidden="true"><span style={{ width: `${(c.spend / totalSpend) * 100}%` }} /></span>
                <span>{money(c.spend)}</span>
              </li>
            ))}
          </ul>
        </Part>

        <Part title="By client" foot="Select a client to light up their towers. Weekly change is the biggest move in cost per conversion across their channels. The five sample clients run on the simulated ad API the spec asked for, priced from published 2026 industry benchmarks; clients you import show their real numbers.">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Client</th>
                  <th scope="col" className="num">Spend</th>
                  <th scope="col" className="num">Conv.</th>
                  <th scope="col" className="num">Cost/conv.</th>
                  <th scope="col" className="num">Weekly</th>
                </tr>
              </thead>
              <tbody>
                {dash.by_client.map((r) => {
                  const w = worst(r.wow);
                  const on = focus === r.client_id;
                  return (
                    <tr key={r.client_id} className={cn(on && "is-focus")}>
                      <th scope="row">
                        <button type="button" className="row-btn" aria-pressed={on}
                          onClick={() => hub.set({ focusClient: on ? null : r.client_id })}>{r.client}</button>
                        {!r.simulated && <span className="badge badge-ok">Imported</span>}
                      </th>
                      <td className="num">{money(r.spend)}</td>
                      <td className="num">{num(r.conversions)}</td>
                      <td className="num">{money(r.cpa, 2)}</td>
                      <td className={cn("num", w != null && w > dash.threshold_pct && "text-signal font-semibold")}>{pct(w)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <SampleBasisNote basis={dash.sample_basis} />
        </Part>

        <Part title="Run it now">
          <div className="mt-3 flex flex-wrap gap-2">
            <Button busy={act.busy === "job"} onClick={runJob}>{act.busy === "job" ? "Running daily job" : "Run the daily job"}</Button>
            <Button variant="secondary" busy={act.busy === "weekly"} onClick={() => writeWeekly(weekly != null)}>
              {weekly ? "Write it again" : "Write the weekly summary"}
            </Button>
          </div>
          <ErrorNote error={act.error} />
          {jobNote && <Note>{jobNote}</Note>}
        </Part>

        <ImportAds />

        {weekly && (
          <Part title={`Weekly summary, week ending ${day(weekly.week)}`} foot={`Written by ${weekly.engine}. Three sentences per client.`}>
            <ul className="summaries">
              {weekly.clients.map((c) => (
                <li key={c.client_id}>
                  <p className="font-semibold">{c.client}</p>
                  <p>{c.sentences.join(" ")}</p>
                </li>
              ))}
            </ul>
          </Part>
        )}
      </Panel>
    </Section>
  );
}

/** Real data in: a Google Ads or Meta export, upserted by client, day and channel. */
function ImportAds() {
  const clients = useHub((s) => s.clients);
  const act = useAction();
  const [file, setFile] = useState<File | null>(null);
  const [channel, setChannel] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return act.setError("Choose a CSV export first.");
    const text = await file.text();
    const r = await act.run("import", () => api.importAds(text, channel));
    if (!r) return;
    setResult(r);
    hub.sendPackets([2, 3]);
    await refresh("dashboard", "log", "status");
  };
  const names = result?.clients.map((id) => clients.find((c) => c.id === id)?.name ?? id).join(", ");

  return (
    <Part title="Import real ad data"
      foot="Google Ads and Meta exports work as they are: date, account or client, cost, clicks and conversions. Campaign lines are added up per day, and importing the same days again replaces them, so nothing is counted twice.">
      <form className="form" onSubmit={submit}>
        <div className="form-row">
          <Field label="CSV export">
            <input type="file" accept=".csv,text/csv" className="input file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Field>
          <Field label="Channel">
            <Select value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="">Read it from the file</option>
              {CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
          </Field>
        </div>
        <Button type="submit" variant="secondary" busy={act.busy === "import"}>{act.busy === "import" ? "Importing" : "Import"}</Button>
      </form>
      <ErrorNote error={act.error} />
      {result && result.date_range && (
        <Note>
          Imported {num(result.days_written)} client-days for {names}, {day(result.date_range[0])} to {day(result.date_range[1])},
          from {num(result.rows_read)} lines. {result.skipped_count === 0 ? "Nothing was skipped." : result.skipped_count === 1 ? "1 line was skipped." : `${result.skipped_count} lines were skipped.`}
        </Note>
      )}
      {result && result.skipped_count > 0 && (
        <details className="skips">
          <summary>Why lines were skipped</summary>
          <ul>{result.skipped.map((x) => <li key={x.line}>Line {x.line}: {x.reason}</li>)}</ul>
        </details>
      )}
    </Part>
  );
}
