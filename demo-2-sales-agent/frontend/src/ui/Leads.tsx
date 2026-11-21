import { useMemo } from "react";
import { SIGNAL_LABELS, type Lead } from "../api";
import { store, useAgent } from "../store";
import { goTo } from "../actions";
import { Panel, Part, Section, StatusBadge } from "./kit";

const host = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; } };
/** Dates are shown only as exactly as the source gives them: a page dated "November 2026" never becomes a made-up day. */
function sourceDate(l: Lead) {
  if (!l.fact_date || l.fact_precision === "none") return "";
  const d = new Date(`${l.fact_date}T00:00:00`);
  if (l.fact_precision === "year") return `, ${d.getFullYear()}`;
  if (l.fact_precision === "month") return `, ${d.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}`;
  return `, ${d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}`;
}
const PARTS: [keyof Lead["score_parts"], string, number][] = [["fit", "Fit", 45], ["signals", "Signals", 35], ["recency", "Recency", 20]];

function Detail({ lead }: { lead: Lead }) {
  return (
    <div className="detail" id={`lead-${lead.id}`}>
      <p>{lead.reason}</p>
      <div>
        <p className="fact">{lead.fact}</p>
        <a className="source link" href={lead.fact_url} target="_blank" rel="noopener noreferrer">
          {host(lead.fact_url)}{sourceDate(lead)}
        </a>
      </div>
      {lead.signals.length > 0 && (
        <div className="chips">{lead.signals.map((s) => <span key={s} className="tag">{SIGNAL_LABELS[s] ?? s}</span>)}</div>
      )}
      <div>
        <p className="small">How the {lead.score} was worked out</p>
        <ul className="parts mt-1">
          {PARTS.map(([key, text, max]) => (
            <li key={key}>
              <span>{text}</span>
              <span className="meter" aria-hidden="true"><span style={{ width: `${(lead.score_parts[key] / max) * 100}%` }} /></span>
              <span>{lead.score_parts[key]} of {max}</span>
            </li>
          ))}
        </ul>
        <p className="small mt-2">{lead.score_reason}</p>
      </div>
      {lead.draft_status ? (
        <p className="small">
          First email: <StatusBadge status={lead.draft_status} />{" "}
          {(lead.draft_status === "pending" || lead.draft_status === "edited") && (
            <button type="button" className="link" onClick={() => { store.set({ focusLead: lead.id }); goTo("queue"); }}>Read the draft</button>
          )}
        </p>
      ) : (
        <p className="small">No email yet. The agent drafts for the top five leads each run.</p>
      )}
    </div>
  );
}

export function Leads() {
  const leads = useAgent((s) => s.leads);
  const focus = useAgent((s) => s.focusLead);
  const sorted = useMemo(() => [...leads].sort((a, b) => b.score - a.score || a.company.localeCompare(b.company)), [leads]);
  const drafted = leads.filter((l) => l.draft_status).length;

  return (
    <Section id="leads" scene={2}>
      <Panel id="leads" title="Leads it found" intro={leads.length
        ? `${leads.length} companies, each scored 0 to 100 by the server from how well they fit, their buying signals and how recent the evidence is. ${drafted} have a drafted email. Every fact links to the page it came from.`
        : "No leads yet. Run the agent and they appear here, highest score first."}>
        {sorted.length > 0 && (
          <Part title="Highest score first">
            <ul className="rows">
              {sorted.map((l) => {
                const open = focus === l.id;
                return (
                  <li key={l.id}>
                    <button type="button" className="row-btn" aria-expanded={open} aria-controls={`lead-${l.id}`}
                      onClick={() => store.set({ focusLead: open ? null : l.id })}>
                      <span>
                        <span className="row-name">{l.company}</span>
                        <span className="row-sub">{l.industry ?? "Industry not stated"}{l.employees ? `, about ${l.employees.toLocaleString("en-US")} staff` : ""}</span>
                      </span>
                      <span className="score" aria-label={`Score ${l.score} out of 100`}>
                        <span>{l.score}</span>
                        <span className="meter" aria-hidden="true"><span style={{ width: `${l.score}%` }} /></span>
                      </span>
                    </button>
                    {open && <Detail lead={l} />}
                  </li>
                );
              })}
            </ul>
          </Part>
        )}
      </Panel>
    </Section>
  );
}
