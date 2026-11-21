import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { api, type Integrity, type Lineage } from "../api";
import { hub, useHub } from "../store";
import { refresh, refreshAll } from "../data";
import { clock } from "../lib/format";
import { Button, ErrorNote, Note, Panel, Part, Section, StatusBadge, useAction } from "./kit";
import { Logo } from "./TopBar";

const humanize = (s: string) => (s.charAt(0).toUpperCase() + s.slice(1)).replace(/_/g, " ");

export function Ops() {
  const log = useHub((s) => s.log);
  const act = useAction();
  const [note, setNote] = useState<string | null>(null);
  const [integrity, setIntegrity] = useState<Integrity | null>(null);
  const [lineage, setLineage] = useState<Lineage | null>(null);
  const [armed, setArmed] = useState(false);

  const fail = async () => {
    const r = await act.run("fail", () => api.forcedFailure());
    if (!r) return;
    setNote(`Logged a test failure: ${r.error}. ${r.slack.sent ? "The alert went to Slack." : "Slack isn't set up, so the alert stays in this log."}`);
    hub.sendPackets(r.slack.sent ? [2, 4] : [2]);
    void refresh("log");
  };
  const check = async () => {
    const r = await act.run("integrity", () => api.integrity());
    if (r) setIntegrity(r);
  };
  const trace = async () => {
    const r = await act.run("lineage", () => api.lineage());
    if (r) setLineage(r);
  };
  const reset = async () => {
    const r = await act.run("reset", () => api.reset());
    setArmed(false);
    if (!r) return;
    hub.set({ site: null, preview: null, focusClient: null });
    setNote(`Demo data is back to ${r.clients} sample clients and ${r.metric_rows} days of ad rows.`);
    setIntegrity(null);
    setLineage(null);
    await refreshAll();
  };

  return (
    <Section id="ops" scene={4}>
      <div className="w-full max-w-[31rem]">
        <Panel id="ops" busy={act.busy !== null} title="Operations"
          intro="Every workflow writes to this log, and failures post to Slack. The checks below prove the numbers add up.">
          <Part title="Activity">
            {log.length ? (
              <ul className="log">
                <AnimatePresence initial={false}>
                  {log.slice(0, 10).map((r) => (
                    <motion.li key={r.id} layout initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                      <time dateTime={r.created_at}>{clock(r.created_at)}</time>
                      <div className="min-w-0">
                        <p className="log-title">{humanize(r.workflow)} <StatusBadge status={r.status} /></p>
                        {(r.error || r.detail) && <p className="small truncate-2">{r.error ?? r.detail}</p>}
                      </div>
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            ) : (
              <p className="small mt-2">Nothing has run yet. Onboard a client or run the daily job.</p>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button variant="secondary" busy={act.busy === "fail"} onClick={fail}>Trigger a test failure</Button>
            </div>
            {note && <Note>{note}</Note>}
          </Part>

          <Part title="Data checks" foot="Read-only. The duplicate-run check works inside a transaction that is rolled back.">
            <div className="mt-3"><Button variant="secondary" busy={act.busy === "integrity"} onClick={check}>Run the checks</Button></div>
            {integrity && (
              <ul className="checks">
                {integrity.checks.map((c) => (
                  <li key={c.name} className={c.ok ? "ok" : "bad"}>
                    <span aria-hidden="true">{c.ok ? "✓" : "✕"}</span>
                    <div><p className="font-semibold">{c.name}<span className="sr-only">{c.ok ? ": passed" : ": failed"}</span></p><p className="small">{c.detail}</p></div>
                  </li>
                ))}
              </ul>
            )}
          </Part>

          <Part title="Where each number comes from" foot="The exact SQL and date window behind every figure on this page.">
            <div className="mt-3"><Button variant="secondary" busy={act.busy === "lineage"} onClick={trace}>Show the SQL</Button></div>
            {lineage && (
              <div className="lineage">
                {lineage.metrics.map((m) => (
                  <details key={m.metric}>
                    <summary>{m.metric}<span className="small">{m.rows} rows</span></summary>
                    <pre className="code"><code>{m.sql.trim()}</code></pre>
                    <p className="small">Parameters: {Object.entries(m.params).map(([k, v]) => `${k} = ${v}`).join(", ")}</p>
                  </details>
                ))}
              </div>
            )}
          </Part>

          <Part title="Training data" foot="Every brief and summary with its inputs, marked unreviewed, ready for evaluation or fine-tuning.">
            <p className="mt-2"><a className="link" href="./api/training-data" download>Download training data (JSONL)</a></p>
          </Part>

          <Part title="Reset the demo">
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {armed ? (
                <>
                  <Button variant="danger" busy={act.busy === "reset"} onClick={reset}>Reset all demo data</Button>
                  <Button variant="quiet" onClick={() => setArmed(false)}>Keep my changes</Button>
                </>
              ) : (
                <Button variant="secondary" onClick={() => setArmed(true)}>Reset demo data</Button>
              )}
            </div>
            {armed && <p className="small mt-2">This removes clients you added and restores the five sample clients with 60 days of ad data.</p>}
          </Part>
          <ErrorNote error={act.error} />
        </Panel>

        <footer className="footer">
          <Logo size={22} />
          <p>A working demo for Northwind Digital. <a className="link" href="https://github.com/umer-78/ai-automation-demos" rel="noopener">Source on GitHub</a></p>
        </footer>
      </div>
    </Section>
  );
}
