import { useMemo, useState, type ChangeEvent } from "react";
import { api, money, type Account, type ImportResult } from "../api";
import { refreshAll } from "../data";
import { store, useAgent } from "../store";
import { day } from "../lib/format";
import { Button, ErrorNote, Field, Input, Note, Panel, Part, Section, Segmented, useAction } from "./kit";

const STAGES = ["Prospecting", "Proposal", "Negotiation", "Customer"];
type View = "stalled" | "untouched" | "upsell" | "top";
// The same colours as the chips on the desk.
const SWATCH = { stalled: "#E3B04B", untouched: "#7E97A6", upsell: "#8CCBF2" };

function Rows({ view, accounts }: { view: View; accounts: Account[] }) {
  const rows = view === "top"
    ? [...accounts].sort((a, b) => b.score - a.score).slice(0, 8)
    : accounts.filter((a) => a.flags.includes(view)).sort((a, b) => b.score - a.score);
  if (!rows.length) return <p className="empty">None right now.</p>;
  const third: Record<View, [string, (a: Account) => string]> = {
    stalled: ["Days in stage", (a) => String(a.days_in_stage)],
    untouched: ["Last contact", (a) => `${a.days_since_contact} days ago`],
    upsell: ["Signal", (a) => a.expansion_signal ?? ""],
    top: ["Score", (a) => String(a.score)],
  };
  const [head, cell] = third[view];
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr><th scope="col">Account</th><th scope="col">Stage</th><th scope="col" className="num">Value</th><th scope="col" className={view === "upsell" ? "" : "num"}>{head}</th></tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{a.company}<span className="why">{view === "top" ? a.score_reason : `${a.owner}. ${a.notes}`}</span></td>
              <td>{a.stage}</td>
              <td className="num">{money(a.deal_value)}</td>
              <td className={view === "upsell" ? "" : "num"}>{cell(a)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Import() {
  const status = useAgent((s) => s.status);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [resetDone, setResetDone] = useState<number | null>(null);
  const { busy, error, setError, run } = useAction();

  const pick = (e: ChangeEvent<HTMLInputElement>) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null); };
  const upload = () => void run("import", async () => {
    if (!file) throw new Error("Choose a CSV file first.");
    if (file.size > 2_000_000) throw new Error("That file is over 2 MB. Export only the columns listed above.");
    const r = await api.importCrm(await file.text());
    setResult(r);
    store.set({ live: null });
    await refreshAll();
  });
  const reset = () => void run("reset", async () => {
    const r = await api.reset();
    setConfirm(false);
    setResult(null);
    setResetDone(r.accounts);
    store.set({ live: null, focusLead: null });
    await refreshAll();
  });

  return (
    <Part title="Use your own CRM" foot={status?.crm_source === "import" ? "Showing your imported accounts. The agent reads them on its next run." : undefined}>
      <p className="small">Export accounts from HubSpot, Salesforce or Pipedrive as a CSV. It needs company, stage and last contact columns; deal value, owner, size, industry and notes are read when present. Importing replaces the sample accounts.</p>
      <div className="form">
        <Field label="CSV export"><Input type="file" accept=".csv,text/csv" className="file" onChange={pick} /></Field>
      </div>
      <div className="actions">
        <Button variant="secondary" busy={busy === "import"} disabled={!file} onClick={upload}>Import accounts</Button>
        {confirm ? (
          <>
            <Button variant="danger" busy={busy === "reset"} onClick={reset}>Clear and reload the sample</Button>
            <Button variant="quiet" onClick={() => setConfirm(false)}>Keep everything</Button>
          </>
        ) : (
          <Button variant="quiet" onClick={() => { setConfirm(true); setResetDone(null); }}>Start over with the sample CRM</Button>
        )}
      </div>
      {confirm && <p className="small mt-2">This clears every lead, draft, decision and run, then reloads the 50 sample accounts.</p>}
      <ErrorNote error={error} />
      {result && (
        <>
          <Note>
            Imported {result.accounts} {result.accounts === 1 ? "account" : "accounts"} from {result.rows_read} {result.rows_read === 1 ? "row" : "rows"}.
            {result.skipped_count > 0 && ` ${result.skipped_count} ${result.skipped_count === 1 ? "row was" : "rows were"} skipped.`}
          </Note>
          {result.skipped.length > 0 && (
            <details className="skips">
              <summary>Why rows were skipped</summary>
              <ul>{result.skipped.map((s) => <li key={s.line}>Line {s.line}: {s.reason}</li>)}</ul>
            </details>
          )}
        </>
      )}
      {resetDone != null && <Note>Back to the sample: {resetDone} accounts, no leads or drafts. Run the agent to start again.</Note>}
    </Part>
  );
}

export function Crm() {
  const accounts = useAgent((s) => s.accounts);
  const crm = useAgent((s) => s.crm);
  const status = useAgent((s) => s.status);
  const [view, setView] = useState<View>("stalled");
  const max = useMemo(() => Math.max(1, ...STAGES.map((s) => crm?.by_stage[s] ?? 0)), [crm]);
  const latest = useMemo(() => accounts.reduce((m, a) => (a.last_contact > m ? a.last_contact : m), ""), [accounts]);

  return (
    <Section id="crm" scene={3}>
      <Panel id="crm" title="The whole CRM, read" intro={crm
        ? `${crm.total} accounts from ${status?.crm_source === "import" ? "your import" : "the sample CRM (fictional companies)"}, last contact logged ${day(latest)}. The agent flags deals sitting in Proposal or Negotiation for 30 days or more, accounts nobody has contacted in over 30 days, and customers showing a reason to buy more.`
        : "Loading the CRM."}>
        {crm && (
          <dl className="kpis">
            <div><dt><span className="swatch" style={{ background: SWATCH.stalled }} aria-hidden="true" />Stalled deals</dt><dd>{crm.stalled}</dd></div>
            <div><dt><span className="swatch" style={{ background: SWATCH.untouched }} aria-hidden="true" />Untouched</dt><dd>{crm.untouched}</dd></div>
            <div><dt><span className="swatch" style={{ background: SWATCH.upsell }} aria-hidden="true" />Upsell signals</dt><dd>{crm.upsell}</dd></div>
          </dl>
        )}
        {crm && (
          <Part title="Accounts by stage" foot="On the desk, each chip is one account, in a row per stage from Prospecting (inside) to Customer (outside).">
            <ul className="bars">
              {STAGES.map((s) => (
                <li key={s}>
                  <span>{s}</span>
                  <span className="bar" aria-hidden="true"><span style={{ width: `${((crm.by_stage[s] ?? 0) / max) * 100}%` }} /></span>
                  <span>{crm.by_stage[s] ?? 0}</span>
                </li>
              ))}
            </ul>
          </Part>
        )}
        {accounts.length > 0 && (
          <Part title="What needs attention">
            <Segmented label="Which accounts" value={view} onChange={setView}
              options={[["stalled", "Stalled"], ["untouched", "Untouched"], ["upsell", "Upsell"], ["top", "Highest scored"]]} />
            <Rows view={view} accounts={accounts} />
            {view !== "top" && <p className="small mt-2">Each run, the agent drafts follow-ups for the most urgent of these. They wait in Approvals with the first emails.</p>}
          </Part>
        )}
        <Import />
      </Panel>
    </Section>
  );
}
