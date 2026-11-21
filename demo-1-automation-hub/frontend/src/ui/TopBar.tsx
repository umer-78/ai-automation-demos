import { useEffect, useRef, useState } from "react";
import { useHub } from "../store";
import { day } from "../lib/format";
import { cn } from "../lib/cn";

const LINKS = [
  { href: "#onboarding", label: "Onboarding", scene: 1 },
  { href: "#reporting", label: "Reporting", scene: 2 },
  { href: "#sites", label: "Website drafts", scene: 3 },
  { href: "#ops", label: "Operations", scene: 4 },
];

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="#0F2A3F" />
      <path d="M7.5 20.5c3.4 0 5-2.3 6.6-4.7S17.5 11 21 11h3.5" fill="none" stroke="#E7EDF1" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M7.5 14c2.4 0 3.7-1.2 4.7-2.6" fill="none" stroke="#5FD3C6" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M17.5 21c1.1-1.4 2.6-2.8 7-2.8" fill="none" stroke="#5FD3C6" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

/** One honest status chip: what's live, what's running in its offline form. */
function StatusChip() {
  const status = useHub((s) => s.status);
  const error = useHub((s) => s.error);
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

  const label = !status ? (error ? "Hub not answering" : "Connecting") : status.live_model ? "Claude live" : "Offline AI engine";
  const tone = !status ? (error ? "bad" : "muted") : status.live_model ? "ok" : "warn";
  const on = (v: boolean, text = "Connected") => (v ? text : "Not set up");
  const rows: [string, string][] = status
    ? [
        ["AI engine", status.engine],
        ["Database", status.database],
        ["Ad data through", day(status.latest_data)],
        ["Airtable", on(status.integrations.airtable)],
        ["Make webhooks", on(status.integrations.make_webhooks, "Protected by token")],
        ["Slack", on(status.integrations.slack)],
        ["Supabase Storage", on(status.integrations.supabase_storage)],
        ["Email", on(status.integrations.email)],
      ]
    : [];

  return (
    <div ref={ref} className="relative">
      <button type="button" className="status-chip" aria-expanded={open} aria-controls="status-pop" onClick={() => setOpen(!open)}>
        <span className={`dot dot-${tone}`} aria-hidden="true" />
        {label}
      </button>
      {open && (
        <div id="status-pop" className="popover" role="dialog" aria-label="Connections">
          {status ? (
            <dl className="facts">
              {rows.map(([k, v]) => (
                <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
              ))}
            </dl>
          ) : (
            <p className="small">{error ?? "Waiting for the hub to answer."}</p>
          )}
          <p className="small mt-3">Anything not set up runs in its offline form. Adding its key on the server switches it on.</p>
        </div>
      )}
    </div>
  );
}

export function TopBar() {
  const section = useHub((s) => s.section);
  const [solid, setSolid] = useState(false);
  useEffect(() => {
    const onScroll = () => setSolid(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <header className={cn("topbar", solid && "is-solid")}>
      <a href="#top" className="brand" aria-label="Northwind Digital, back to top">
        <Logo />
        <span>Northwind Digital</span>
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
