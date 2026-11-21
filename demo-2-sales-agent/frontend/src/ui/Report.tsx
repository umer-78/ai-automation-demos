import { money } from "../api";
import { useAgent } from "../store";
import { clock, day } from "../lib/format";
import { Button, Panel, Part, Section } from "./kit";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function Report() {
  const report = useAgent((s) => s.report);
  const imported = useAgent((s) => s.status?.crm_source === "import");
  const c = report?.counts;
  const kpis: [string, number][] = c ? [
    ["New leads", c.new_leads], ["Waiting for you", c.waiting], ["Approved", c.approved],
    ["Stalled deals", c.stalled], ["Untouched accounts", c.untouched], ["Upsell signals", c.upsell],
  ] : [];
  const d = report?.decisions;

  return (
    <Section id="report" scene={5}>
      <Panel id="report" title="This week, on one page" intro={report
        ? `${day(report.week.start)} to ${day(report.week.end)}. Built from the database when you open it, generated ${day(report.generated_at)} at ${clock(report.generated_at)}.`
        : "Loading the report."}>
        {c && (
          <dl className="kpis">
            {kpis.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v.toLocaleString("en-US")}</dd></div>)}
          </dl>
        )}
        {report && report.top_leads.length > 0 && (
          <Part title="Best new leads">
            <ol className="ranked">
              {report.top_leads.map((l) => (
                <li key={l.id}>
                  <span><b>{l.company}</b><span className="why">{l.reason}</span></span>
                  <span>{l.score}</span>
                </li>
              ))}
            </ol>
          </Part>
        )}
        {report && report.top_accounts.length > 0 && (
          <Part title="CRM accounts to call first">
            <ol className="ranked">
              {report.top_accounts.map((a) => (
                <li key={a.id}>
                  <span><b>{a.company}</b><span className="why">{a.score_reason}</span></span>
                  <span>{money(a.deal_value)}</span>
                </li>
              ))}
            </ol>
          </Part>
        )}
        {report && d && (
          <Part title="Your decisions this week">
            <p className="text-sm">
              {d.approve + d.edit + d.reject === 0
                ? "No decisions yet. Approve, edit or reject drafts in Approvals and they're counted here."
                : `${plural(d.approve, "approval")}, ${plural(d.edit, "edit")} and ${plural(d.reject, "rejection")}. Edits and rejections are read by the agent before its next run.`}
            </p>
            {report.last_run && (
              <p className="small mt-2">
                Last run {day(report.last_run.started_at)} at {clock(report.last_run.started_at)}: {report.last_run.outcome ?? report.last_run.error ?? report.last_run.status}
              </p>
            )}
          </Part>
        )}
        <div className="actions no-print">
          <Button variant="secondary" onClick={() => window.print()}>Print or save as PDF</Button>
        </div>
        <p className="footer">
          A proof of concept built by Umer for Acme Cloud Security. {imported ? "The CRM accounts are from your import" : "The CRM accounts are fictional"};
          the leads and their facts come from real, linked web pages. <a className="link" href="https://github.com/umer-78/ai-automation-demos" target="_blank" rel="noopener noreferrer">Source on GitHub</a>
        </p>
      </Panel>
    </Section>
  );
}
