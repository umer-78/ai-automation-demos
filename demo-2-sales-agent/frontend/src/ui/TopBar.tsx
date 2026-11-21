import { useEffect, useRef, useState } from "react";
import { useAgent } from "../store";
import { day } from "../lib/format";
import { cn } from "../lib/cn";

const LINKS = [
  { href: "#run", label: "Run", scene: 1 },
  { href: "#leads", label: "Leads", scene: 2 },
  { href: "#crm", label: "CRM", scene: 3 },
  { href: "#queue", label: "Approvals", scene: 4 },
  { href: "#report", label: "Report", scene: 5 },
];

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="#E3B04B" />
      <path d="M16 6.5 24.5 10v6.2c0 4.9-3.5 8.3-8.5 9.8-5-1.5-8.5-4.9-8.5-9.8V10Z" fill="#12302B" />
      <path d="M12 16.4l2.9 2.9 5.4-5.8" fill="none" stroke="#E3B04B" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** One honest status chip: what's live and what's running in its offline form. */
function StatusChip() {
  const status = useAgent((s) => s.status);
  const error = useAgent((s) => s.error);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const label = !status ? (error ? "Server not answering" : "Connecting") : status.live_model ? "Claude live" : "Offline agent";
  const tone = !status ? (error ? "bad" : "muted") : status.live_model ? "ok" : "warn";
  const rows: [string, string][] = status
    ? [
        ["Agent", status.engine],
        ["Web research", status.live_search ? "Live Tavily search" : `Saved search results from ${day(status.snapshot_date)}`],
        ["CRM data", status.crm_source === "import" ? "Your imported CSV" : "Sample CRM, 50 fictional accounts"],
        ["Database", status.database],
        ["Slack alerts", status.slack ? "Connected" : "Not set up"],
        ["Sending email", "Never. You download approved emails and send them yourself."],
      ]
    : [];

  return (
    <div ref={ref} className="relative">
      <button type="button" className="status-chip" aria-expanded={open} aria-controls="status-pop" onClick={() => setOpen(!open)}>
        <span className={`dot dot-${tone}`} aria-hidden="true" />
        {label}
      </button>
      {open && (
        <div id="status-pop" className="popover" role="dialog" aria-label="What's connected">
          {status ? (
            <dl className="facts">
              {rows.map(([k, v]) => (
                <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
              ))}
            </dl>
          ) : (
            <p className="small">{error ?? "Waiting for the server to answer."}</p>
          )}
          <p className="small mt-3">Adding a Claude or Tavily key on the server switches that part to live. Nothing else changes.</p>
        </div>
      )}
    </div>
  );
}

export function TopBar() {
  const section = useAgent((s) => s.section);
  const [solid, setSolid] = useState(false);
  useEffect(() => {
    const onScroll = () => setSolid(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <header className={cn("topbar", solid && "is-solid")}>
      <a href="#top" className="brand" aria-label="Acme Cloud Security sales agent, back to top">
        <Logo />
        <span>Acme Cloud Security</span>
      </a>
      <nav aria-label="Sections" className="nav">
        {LINKS.map((l) => (
          <a key={l.href} href={l.href} aria-current={section === l.scene ? "true" : undefined}>{l.label}</a>
        ))}
      </nav>
      <StatusChip />
    </header>
  );
}
