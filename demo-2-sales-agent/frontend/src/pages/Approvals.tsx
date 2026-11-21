import clsx from "clsx";
import { Check, Copy, Download, ExternalLink, PencilLine, Send, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button, Chip, Empty, ErrorNote, FlagChip, PageHeader, ScoreBar, Skeleton, Stamp, StatusChip, Tabs, Tilt, useToast } from "../components/ui";
import { api, PREVIEW, type Draft } from "../lib/api";
import { dayMonth, hostOf, LESSON_LABEL, timeAgo, wordCount } from "../lib/format";
import { dataChanged, useApi, useOnDataChanged, usePrefersReducedMotion } from "../lib/hooks";

type Filter = "pending" | "ready" | "rejected" | "sent";
/** Review actions that put a stamp on the draft; the queue moves on once the stamp has landed. */
const STAMPED = new Set(["approve", "edit", "reject", "sent"]);

function stampOf(d: Draft): { kind: "approved" | "sent" | "returned"; note?: string | null } | null {
  if (d.status === "sent") return { kind: "sent" };
  if (d.status === "approved" || d.status === "edited") return { kind: "approved", note: d.status === "edited" ? "with your edits" : null };
  if (d.status === "rejected") {
    const reason = [...(d.feedback ?? [])].reverse().find((f) => f.action === "reject")?.reason;
    return { kind: "returned", note: reason };
  }
  return null;
}
const FILTER_STATUSES: Record<Filter, string[]> = { pending: ["pending"], ready: ["approved", "edited"], rejected: ["rejected"], sent: ["sent"] };

function QueueItem({ d, active, onClick }: { d: Draft; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-current={active}
      className={clsx(
        "w-full border-l-[3px] px-4 py-3 text-left transition-colors",
        active ? "border-amber bg-sheet" : "border-transparent hover:bg-spruce/[0.035]",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="heading truncate text-[15px]">{d.company}</span>
        <span className="shrink-0 text-[12px] text-ink-3">{d.kind === "outreach" ? "First email" : "Follow-up"}</span>
      </div>
      <p className="mt-0.5 truncate text-[13.5px] text-ink-2">{d.subject}</p>
      <div className="mt-1 flex items-center gap-2 text-[12px] text-ink-3">
        {d.kind === "outreach" && d.lead_score !== null && d.lead_score !== undefined && <span className="num">score {d.lead_score}</span>}
        {d.kind === "follow_up" && d.send_date && <span>send {dayMonth(d.send_date)}</span>}
        <span>{timeAgo(d.created_at)}</span>
        {d.previous_draft_id && <Chip tone="sage" className="!px-1.5 !py-0 !text-[11px]">rewrite</Chip>}
      </div>
    </button>
  );
}

function DraftView({ id, onDone }: { id: number; onDone: (next?: boolean) => void }) {
  const { data: d, error, reload } = useApi<Draft>(`/api/drafts/${id}`);
  const toast = useToast();
  const [mode, setMode] = useState<"view" | "edit" | "reject">("view");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState(() => {
    try {
      return localStorage.getItem("acme-reviewer") ?? "";
    } catch {
      return "";
    }
  });
  const reduced = usePrefersReducedMotion();
  // the queue only moves on if the reviewer is still looking at this draft when the stamp lands
  const shownId = useRef(id);
  const mounted = useRef(true);
  useEffect(() => {
    shownId.current = id;
  }, [id]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const seen = useRef<{ id: number; status: string } | null>(null);
  const press = !!d && seen.current?.id === d.id && seen.current.status !== d.status;
  useEffect(() => {
    if (d) seen.current = { id: d.id, status: d.status };
  }, [d]);

  useEffect(() => {
    setMode("view");
    setReason("");
  }, [id]);
  useEffect(() => {
    if (d) {
      setSubject(d.subject);
      setBody(d.body);
    }
  }, [d]);

  const act = async (name: string, fn: () => Promise<unknown>, message: string, advance = true) => {
    setBusy(name);
    try {
      try {
        if (reviewer) localStorage.setItem("acme-reviewer", reviewer);
      } catch {
        // private browsing: the name is simply not remembered
      }
      const startedOn = id;
      await fn();
      toast("success", message);
      setMode("view");
      await reload();
      // let the stamp land before the queue moves on
      if (STAMPED.has(name) && !reduced) await new Promise((r) => window.setTimeout(r, 900));
      dataChanged();
      if (mounted.current && shownId.current === startedOn) onDone(advance);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  if (error) return <ErrorNote message={error} />;
  if (!d) return <Skeleton className="h-[520px] w-full" />;
  const who = reviewer.trim() || undefined;
  const ready = d.status === "approved" || d.status === "edited";
  const lessons = (d.lessons_applied ?? []).filter((k) => LESSON_LABEL[k]);
  const stamp = stampOf(d);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="display text-[28px]">{d.company}</h2>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <StatusChip status={d.status} />
            <Chip tone="neutral">{d.kind === "outreach" ? "First email to a new lead" : `Follow-up, ${d.account_stage}`}</Chip>
            <Chip tone={d.generated_by === "ai" ? "amber" : "neutral"}>{d.generated_by === "ai" ? "Written by the AI agent" : "Written by the offline planner"}</Chip>
            {(d.account_flags ?? []).map((f) => (
              <FlagChip key={f} flag={f} />
            ))}
          </div>
        </div>
        {d.kind === "outreach" && d.lead_score !== null && d.lead_score !== undefined && (
          <div className="w-56">
            <ScoreBar parts={d.lead_score_parts} score={d.lead_score} size="sm" />
          </div>
        )}
      </div>

      <section className="rounded-xl border border-amber/40 bg-amber-soft/60 px-4 py-3">
        {d.kind === "outreach" ? (
          <>
            <div className="text-[13px] font-semibold text-amber-ink">The fact this email uses</div>
            <p className="mt-0.5 text-[15px]">{d.cited_fact}</p>
            {d.source_url && (
              <a href={d.source_url} target="_blank" rel="noreferrer" className="link mt-1 inline-flex items-center gap-1 text-[13.5px]">
                Source: {hostOf(d.source_url)} <ExternalLink className="size-3.5" aria-hidden />
              </a>
            )}
          </>
        ) : (
          <>
            <div className="text-[13px] font-semibold text-amber-ink">Recommended next step</div>
            <p className="mt-0.5 text-[15px]">{d.next_step}</p>
            <p className="mt-1 text-[13.5px] text-ink-2">Suggested send date: {dayMonth(d.send_date)}. Owner {d.account_owner}.</p>
          </>
        )}
      </section>

      <Tilt disabled={mode === "edit"} max={2.2}>
        <article className="sheet relative">
          {stamp && <Stamp key={`${d.id}-${stamp.kind}`} kind={stamp.kind} note={stamp.note} press={press} />}
          <div className="space-y-1.5 border-b border-rule-soft px-5 py-3 text-[14px]">
            <div className="grid grid-cols-[64px_1fr] gap-2">
              <span className="text-ink-3">To</span>
              <span>{d.recipient ? `${d.recipient_name} <${d.recipient}>` : <span className="text-ink-3">You choose the recipient when you send it. The agent never invents contact details.</span>}</span>
            </div>
            <div className="grid grid-cols-[64px_1fr] items-center gap-2">
              <span className="text-ink-3">Subject</span>
              {mode === "edit" ? (
                <input className="field !py-1.5" value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" />
              ) : (
                <span className="font-semibold">{d.subject}</span>
              )}
            </div>
          </div>
          {mode === "edit" ? (
            <div className="p-4">
              <textarea className="field min-h-[300px] resize-y font-[inherit] leading-relaxed" value={body} onChange={(e) => setBody(e.target.value)} aria-label="Email body" />
              <div className="mt-1 text-right text-[12.5px] text-ink-3">{wordCount(body)} words</div>
            </div>
          ) : (
            <div className="whitespace-pre-wrap px-5 py-4 text-[15px] leading-relaxed">{d.body}</div>
          )}
        </article>
      </Tilt>

      <div className="flex flex-wrap items-center gap-2 text-[13px] text-ink-3">
        <span className="num">{d.word_count ?? wordCount(d.body)} words</span>
        {lessons.length > 0 && <span>Learned from feedback:</span>}
        {lessons.map((k) => (
          <Chip key={k} tone="sage">
            {LESSON_LABEL[k]}
          </Chip>
        ))}
        {d.previous_draft_id && (
          <Link to="/learning" className="link">
            Rewrite of a rejected draft
          </Link>
        )}
      </div>

      {(d.status === "pending" || mode === "edit") && (
        <label className="block max-w-xs text-[13px] text-ink-3">
          Reviewer name (optional)
          <input className="field mt-1 !py-1.5" value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Your name" maxLength={60} />
        </label>
      )}

      {d.status === "pending" && mode === "view" && (
        <div className="flex flex-wrap gap-2">
          <Button variant="approve" icon={<Check className="size-4" />} busy={busy === "approve"} onClick={() => act("approve", () => api.post(`/api/drafts/${d.id}/approve`, { reviewer: who }), "Approved. It is ready to send by hand.")}>
            Approve
          </Button>
          <Button icon={<PencilLine className="size-4" />} onClick={() => setMode("edit")}>
            Edit
          </Button>
          <Button variant="danger" icon={<X className="size-4" />} onClick={() => setMode("reject")}>
            Reject
          </Button>
        </div>
      )}

      {mode === "edit" && (
        <div className="space-y-3 rounded-xl border border-rule bg-sheet p-4">
          <label className="block text-[14px] font-semibold">
            What did you change and why? (optional, the agent reads it next run)
            <input className="field mt-1" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} placeholder="For example: shorter, and no meeting ask in a first email" />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="approve"
              busy={busy === "edit"}
              disabled={subject.trim().length < 3 || wordCount(body) < 5}
              onClick={() => act("edit", () => api.post(`/api/drafts/${d.id}/edit`, { subject, body, reason: reason || undefined, reviewer: who }), "Edit saved and approved.")}
            >
              Save edit and approve
            </Button>
            <Button variant="ghost" onClick={() => { setMode("view"); setSubject(d.subject); setBody(d.body); }}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {mode === "reject" && (
        <form
          className="space-y-3 rounded-xl border border-crimson/30 bg-crimson-soft/60 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void act("reject", () => api.post(`/api/drafts/${d.id}/reject`, { reason, reviewer: who }), "Rejected. The reason goes into the next run.");
          }}
        >
          <label className="block text-[14px] font-semibold">
            One-line reason (required, the agent reads it on the next run)
            <input autoFocus className="field mt-1" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} placeholder="For example: too long, and do not ask for a meeting" />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="danger" busy={busy === "reject"} disabled={reason.trim().length < 3}>
              Reject with this reason
            </Button>
            <Button type="button" variant="ghost" onClick={() => setMode("view")}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {ready && mode === "view" && (
        <div className="space-y-3 rounded-xl border border-moss/30 bg-moss-soft/60 p-4">
          <p className="text-[14px]">
            Approved by {d.reviewer ?? "a rep"} {d.reviewed_at ? timeAgo(d.reviewed_at) : ""}. Send it from your own inbox, then mark it as sent.
          </p>
          <div className="flex flex-wrap gap-2">
            {!PREVIEW && (
              <a href={api.url(`/api/drafts/${d.id}/eml`)} className="inline-flex h-10 items-center gap-2 rounded-lg border border-rule bg-sheet px-4 text-[14px] font-semibold hover:border-ink-3/50">
                <Download className="size-4" /> Download .eml
              </a>
            )}
            <Button
              icon={<Copy className="size-4" />}
              onClick={() => {
                void navigator.clipboard
                  .writeText(`Subject: ${d.subject}\n\n${d.body}`)
                  .then(() => toast("success", "Copied subject and body."))
                  .catch(() => toast("error", "The browser blocked the clipboard. Select the text and copy it instead."));
              }}
            >
              Copy text
            </Button>
            <Button variant="dark" icon={<Send className="size-4" />} busy={busy === "sent"} onClick={() => act("sent", () => api.post(`/api/drafts/${d.id}/mark-sent`, { reviewer: who }), "Marked as sent.", false)}>
              I sent it, mark as sent
            </Button>
            {d.status === "approved" && (
              <Button variant="ghost" icon={<PencilLine className="size-4" />} onClick={() => setMode("edit")}>
                Edit again
              </Button>
            )}
          </div>
        </div>
      )}

      {(d.feedback ?? []).length > 0 && (
        <section>
          <h3 className="heading mb-2 text-[15px]">Review history</h3>
          <ul className="space-y-1.5 text-[14px]">
            {(d.feedback ?? []).map((f) => (
              <li key={f.id} className="flex flex-wrap gap-x-2">
                <span className="font-semibold">{{ approve: "Approved", edit: "Edited", reject: "Rejected", mark_sent: "Marked as sent" }[f.action]}</span>
                <span className="text-ink-3">by {f.reviewer ?? "a rep"}, {timeAgo(f.created_at)}</span>
                {f.reason && <span className="text-ink-2">"{f.reason}"</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

const tabOf = (status: string): Filter => (Object.keys(FILTER_STATUSES) as Filter[]).find((f) => FILTER_STATUSES[f].includes(status)) ?? "pending";

export default function Approvals() {
  const [params, setParams] = useSearchParams();
  const { data, error, reload } = useApi<Draft[]>("/api/drafts");
  useOnDataChanged(useCallback(() => void reload(), [reload]));
  const selectedId = params.get("draft") ? Number(params.get("draft")) : null;

  const groups = useMemo(() => {
    const rank = (d: Draft) => (d.kind === "outreach" ? `0-${String(999 - (d.lead_score ?? 0)).padStart(3, "0")}` : `1-${d.send_date ?? ""}`);
    const all = [...(data ?? [])].sort((a, b) => (a.status === "pending" && b.status === "pending" ? rank(a).localeCompare(rank(b)) : 0));
    return Object.fromEntries((Object.keys(FILTER_STATUSES) as Filter[]).map((f) => [f, all.filter((d) => FILTER_STATUSES[f].includes(d.status))])) as Record<Filter, Draft[]>;
  }, [data]);

  // The URL is the single source of truth: ?tab=ready&draft=12. A deep link without a tab opens the draft's own tab.
  const linked = selectedId && data ? data.find((d) => d.id === selectedId) : undefined;
  const tabParam = params.get("tab") as Filter | null;
  const filter: Filter = tabParam && tabParam in FILTER_STATUSES ? tabParam : linked ? tabOf(linked.status) : "pending";
  const list = groups[filter];

  useEffect(() => {
    if (!data) return;
    if (selectedId && list.some((d) => d.id === selectedId)) return;
    const first = list[0];
    if (first) setParams({ tab: filter, draft: String(first.id) }, { replace: true });
  }, [data, selectedId, list, filter, setParams]);

  const select = (id: number) => setParams({ tab: filter, draft: String(id) });
  const onDone = (advance?: boolean) => {
    if (!advance) return;
    const idx = list.findIndex((d) => d.id === selectedId);
    const next = list[idx + 1] ?? list[idx - 1];
    if (next) select(next.id);
  };

  return (
    <div>
      <PageHeader
        title="Approval queue"
        description="Every email the agent writes waits here. Approve it, edit it or reject it with a reason. Approved emails are sent by you from your own inbox, never by the app."
      />
      {error && <ErrorNote message={error} />}
      <Tabs
        label="Draft status"
        value={filter}
        onChange={(f) => setParams({ tab: f })}
        options={[
          { value: "pending", label: "Waiting", count: groups.pending.length },
          { value: "ready", label: "Ready to send", count: groups.ready.length },
          { value: "rejected", label: "Rejected", count: groups.rejected.length },
          { value: "sent", label: "Sent", count: groups.sent.length },
        ]}
      />
      {!data ? (
        <Skeleton className="mt-6 h-96 w-full" />
      ) : list.length === 0 ? (
        <div className="mt-6">
          <Empty title={filter === "pending" ? "Nothing waiting for approval" : "Nothing here yet"}>
            {filter === "pending" ? "Run the agent to research leads and draft emails. New drafts land here." : "Drafts move here as you review them."}
          </Empty>
        </div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[320px_1fr]">
          <nav aria-label="Drafts" className="panel max-h-[78vh] divide-y divide-rule-soft overflow-y-auto">
            {list.map((d) => (
              <QueueItem key={d.id} d={d} active={d.id === selectedId} onClick={() => select(d.id)} />
            ))}
          </nav>
          <div className="min-w-0">{selectedId && list.some((d) => d.id === selectedId) ? <DraftView id={selectedId} onDone={onDone} /> : <Skeleton className="h-96 w-full" />}</div>
        </div>
      )}
    </div>
  );
}
