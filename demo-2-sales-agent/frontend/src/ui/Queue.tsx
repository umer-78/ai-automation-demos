import { useCallback, useEffect, useState } from "react";
import { api, type Draft, type ProofPair } from "../api";
import { refresh } from "../data";
import { store, useAgent } from "../store";
import { day } from "../lib/format";
import { Button, ErrorNote, Field, Input, Note, Panel, Part, Section, Select, StatusBadge, TextArea, useAction } from "./kit";

const words = (s: string) => s.trim().split(/\s+/).filter(Boolean).length;
const host = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; } };
const kindLabel = (d: Draft) => (d.kind === "first_touch" ? "First email" : `Follow-up${d.due_date ? `, send by ${day(d.due_date)}` : ""}`);
type Mode = "read" | "edit" | "reject";
type Done = { id: number; company: string; action: "approved" | "edited" | "rejected" } | null;

function Why({ d }: { d: Draft }) {
  const fromCrm = d.fact_url.startsWith("crm:");
  return (
    <div className="why-box">
      <p><b>Why this email.</b> {d.fact}</p>
      <p className="small mt-1">
        {fromCrm ? `From the CRM record for ${d.company}${d.account_owner ? `, owned by ${d.account_owner}` : ""}.`
          : <>Source: <a className="link" href={d.fact_url} target="_blank" rel="noopener noreferrer">{host(d.fact_url)}</a>{d.lead_score != null && `. Lead score ${d.lead_score} of 100.`}</>}
        {d.next_step && ` Suggested next step: ${d.next_step}`}
      </p>
    </div>
  );
}

function Letter({ d, onDone }: { d: Draft; onDone: (done: Done) => void }) {
  const [mode, setMode] = useState<Mode>("read");
  const [subject, setSubject] = useState(d.subject);
  const [body, setBody] = useState(d.body);
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  useEffect(() => { setMode("read"); setSubject(d.subject); setBody(d.body); setReason(""); }, [d.id, d.subject, d.body]);

  const approve = () => void run("approve", async () => {
    await api.approve(d.id);
    store.seal(true);
    onDone({ id: d.id, company: d.company, action: "approved" });
  });
  const save = () => void run("edit", async () => {
    await api.edit(d.id, subject, body);
    setMode("read");
    onDone({ id: d.id, company: d.company, action: "edited" });
  });
  const reject = () => void run("reject", async () => {
    await api.reject(d.id, reason.trim());
    store.seal(false);
    onDone({ id: d.id, company: d.company, action: "rejected" });
  });

  return (
    <>
      <article className="letter" aria-label={`Draft to ${d.company}`}>
        <div className="letter-meta">
          <span>To {d.company}</span>
          <span>{kindLabel(d)}</span>
        </div>
        {mode === "edit" ? (
          <div className="form">
            <Field label="Subject"><Input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={200} /></Field>
            <Field label="Email"><TextArea rows={10} value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000} /></Field>
          </div>
        ) : (
          <>
            <h3 className="letter-subject">{d.subject}</h3>
            <p className="letter-body">{d.body}</p>
          </>
        )}
      </article>
      <Why d={d} />
      {mode === "reject" && (
        <div className="form">
          <Field label="Why reject it?" hint="The agent reads your reason before its next run, so be specific.">
            <TextArea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} maxLength={300} placeholder="Too long, and it should ask for a 15-minute call" />
          </Field>
        </div>
      )}
      <div className="actions">
        {mode === "read" && (
          <>
            <Button busy={busy === "approve"} onClick={approve}>Approve</Button>
            <Button variant="secondary" onClick={() => setMode("edit")}>Edit</Button>
            <Button variant="quiet" onClick={() => setMode("reject")}>Reject</Button>
          </>
        )}
        {mode === "edit" && (
          <>
            <Button busy={busy === "edit"} disabled={!subject.trim() || !body.trim()} onClick={save}>Save changes</Button>
            <Button variant="quiet" onClick={() => setMode("read")}>Cancel</Button>
          </>
        )}
        {mode === "reject" && (
          <>
            <Button variant="danger" busy={busy === "reject"} disabled={reason.trim().length < 3} onClick={reject}>Reject draft</Button>
            <Button variant="quiet" onClick={() => setMode("read")}>Cancel</Button>
          </>
        )}
      </div>
      <ErrorNote error={error} />
    </>
  );
}

function DoneNote({ done }: { done: Done }) {
  if (!done) return null;
  if (done.action === "approved") return (
    <Note>
      Approved the email to {done.company}. <a className="link" href={`./api/drafts/${done.id}/eml`} download>Download it as an email file</a> and
      send it from your own mail app. This page never sends anything.
    </Note>
  );
  if (done.action === "edited") return <Note>Saved your edit to the {done.company} email. Approve it when it reads right; the agent learns from what you changed.</Note>;
  return <Note>Rejected the {done.company} draft. The agent reads your reason before its next run.</Note>;
}

export function Queue() {
  const queue = useAgent((s) => s.queue);
  const focusLead = useAgent((s) => s.focusLead);
  const [index, setIndex] = useState(0);
  const [done, setDone] = useState<Done>(null);
  const [approved, setApproved] = useState<Draft[]>([]);
  const [proof, setProof] = useState<ProofPair[]>([]);

  const loadSide = useCallback(() => {
    void api.drafts("approved").then(setApproved).catch(() => undefined);
    void api.proof().then(setProof).catch(() => undefined);
  }, []);
  useEffect(loadSide, [loadSide, queue.length]);

  // "Read the draft" on a lead jumps straight to its email.
  useEffect(() => {
    if (focusLead == null) return;
    const at = queue.findIndex((d) => d.lead_id === focusLead);
    if (at >= 0) setIndex(at);
  }, [focusLead, queue]);
  const current = queue[Math.min(index, queue.length - 1)];

  const onDone = (d: Done) => {
    setDone(d);
    // An approved or rejected draft leaves the queue at once; the server copy follows.
    if (d && d.action !== "edited") store.set({ queue: store.get().queue.filter((q) => q.id !== d.id) });
    void refresh("queue", "leads", "status", "report").then(loadSide);
  };

  return (
    <Section id="queue" scene={4}>
      <Panel id="queue" title="Waiting for your approval" intro={queue.length
        ? `${queue.length} ${queue.length === 1 ? "draft" : "drafts"}. Nothing is sent from here: approving makes an email file you send yourself, and every edit or rejection is feedback for the next run.`
        : "Nothing waiting. Run the agent to get new drafts."}>
        <DoneNote done={done} />
        {current && (
          <>
            <div className="pager">
              <Button variant="secondary" disabled={index <= 0} onClick={() => setIndex(index - 1)} aria-label="Previous draft">Previous</Button>
              <Select aria-label="Choose a draft" value={current.id} onChange={(e) => setIndex(queue.findIndex((d) => d.id === Number(e.target.value)))}>
                {queue.map((d, i) => <option key={d.id} value={d.id}>{i + 1} of {queue.length}: {d.company}, {d.kind === "first_touch" ? "first email" : "follow-up"}</option>)}
              </Select>
              <Button variant="secondary" disabled={index >= queue.length - 1} onClick={() => setIndex(index + 1)} aria-label="Next draft">Next</Button>
            </div>
            {current.status === "edited" && <p className="small mt-3"><StatusBadge status="edited" /> You changed this one. It still needs your approval.</p>}
            <Letter key={current.id} d={current} onDone={onDone} />
          </>
        )}
        {proof.length > 0 && (
          <Part title="What your feedback changed">
            <p className="small">The newest draft to the same company, written after you {proof[0].feedback.action === "reject" ? "rejected" : "edited"} the earlier one.</p>
            <div className="compare">
              {proof.slice(0, 2).map((p) => (
                <div key={p.before.id}>
                  <p className="text-sm"><b>{p.company}</b>{p.feedback.reason ? `. You said: "${p.feedback.reason}"` : ". You edited it."}</p>
                  <details><summary>Before, {words(p.before.original_body)} words</summary><pre>{p.before.original_body}</pre></details>
                  <details><summary>After, {words(p.after.body)} words</summary><pre>{p.after.body}</pre></details>
                </div>
              ))}
            </div>
          </Part>
        )}
        {approved.length > 0 && (
          <Part title="Approved and ready to send">
            <ul className="rows">
              {approved.slice(0, 6).map((d) => (
                <li key={d.id} className="flex items-center justify-between gap-4 py-2">
                  <span><span className="row-name">{d.company}</span><span className="row-sub">{d.subject}</span></span>
                  <a className="link shrink-0 text-sm" href={`./api/drafts/${d.id}/eml`} download>Download</a>
                </li>
              ))}
            </ul>
          </Part>
        )}
      </Panel>
    </Section>
  );
}
