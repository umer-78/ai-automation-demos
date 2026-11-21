import clsx from "clsx";
import { Radar } from "lucide-react";
import { Suspense, lazy, useCallback, useEffect, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { accessCode, isLocked, onLockChange, setAccessCode, type Overview } from "../lib/api";
import { timeAgo } from "../lib/format";
import { useApi, useDataStatus, useOnDataChanged } from "../lib/hooks";
import { useRun } from "../lib/run";
import { usePageMeta } from "../lib/seo";
import { Button } from "./ui";
// the 3D world loads after the page text, so words and numbers paint first
const World = lazy(() => import("../world/World"));

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/approvals", label: "Approvals" },
  { to: "/leads", label: "Leads" },
  { to: "/accounts", label: "CRM" },
  { to: "/learning", label: "Learning" },
  { to: "/report", label: "Report" },
  { to: "/runs", label: "Runs" },
  { to: "/profile", label: "Ideal customer" },
  { to: "/settings", label: "Settings" },
];

export function Logo() {
  return (
    <NavLink to="/" className="flex shrink-0 items-center gap-2.5 text-[16px] font-semibold tracking-[-0.02em]" aria-label="Sales agent, home">
      <svg viewBox="0 0 32 32" className="size-[22px]" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#0a0a0a" />
        <circle cx="16" cy="16" r="9" fill="none" stroke="#ffffff" strokeOpacity="0.55" strokeWidth="1.6" />
        <circle cx="16" cy="16" r="4.2" fill="none" stroke="#ffffff" strokeOpacity="0.55" strokeWidth="1.6" />
        <path d="M16 16 L23.8 11.5 A9 9 0 0 1 25 16 Z" fill="#f5a524" />
      </svg>
      Sales agent
    </NavLink>
  );
}

export function RunButton({ size = "md", className }: { size?: "md" | "lg"; className?: string }) {
  const { start, busy } = useRun();
  return (
    <Button variant="signal" size={size} className={className} onClick={() => void start()} busy={busy} icon={<Radar className="size-[18px]" aria-hidden />}>
      {busy ? "Agent running" : "Run agent"}
    </Button>
  );
}

/** Which CRM the numbers come from, and when it last synced. */
function DataLabel() {
  const d = useDataStatus();
  if (!d) return null;
  const detail = d.mode === "real" && d.last_sync ? `${d.last_sync.kind === "hubspot_sync" ? "synced" : "imported"} ${timeAgo(d.last_sync.at)}` : null;
  return (
    <div className="hidden items-center gap-2 text-[13.5px] text-ink-3 lg:flex" title={d.mode === "demo" ? "Acme and its 50 accounts are fictional. The leads are real companies with real sources." : "Your own accounts"}>
      {d.mode === "demo" ? <span className="size-2 rounded-full bg-amber" /> : <span className="live-dot" />}
      <span className="font-medium text-ink">{d.label}</span>
      {detail && <span className="num">{detail}</span>}
    </div>
  );
}

/** Your own CRM needs the owner's (or a teammate's) access code before anything loads. */
function AccessGate() {
  const [locked, setLocked] = useState(isLocked);
  const [code, setCode] = useState("");
  useEffect(() => onLockChange(() => setLocked(isLocked())), []);
  if (!locked) return null;
  const tried = Boolean(accessCode());
  function open(e: FormEvent) {
    e.preventDefault();
    setAccessCode(code);
    window.location.reload();
  }
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="gate-title" className="fixed inset-0 z-50 grid place-items-center bg-paper/80 px-4 backdrop-blur-md">
      <form onSubmit={open} className="w-full max-w-[420px] rounded-[22px] bg-white p-7 shadow-[0_30px_80px_-40px_rgba(15,20,30,0.45)] ring-1 ring-black/[0.06]">
        <h2 id="gate-title" className="text-[22px] font-semibold tracking-[-0.02em]">Your CRM data</h2>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-2">This app runs on your own accounts and drafts. Enter the access code to open it.</p>
        <input autoFocus type="password" autoComplete="current-password" className="field mt-4" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Access code" aria-label="Access code" />
        {tried && <p className="mt-2 text-[13.5px] text-crimson">That code did not open the app. Check it with the owner.</p>}
        <button type="submit" disabled={!code.trim()} className="mt-4 inline-flex min-h-11 w-full items-center justify-center rounded-[11px] bg-black px-[18px] text-[15px] font-medium text-white disabled:opacity-50">
          Open the app
        </button>
      </form>
    </div>
  );
}

export default function Layout() {
  const { data, reload } = useApi<Overview>("/api/overview", 20000);
  useOnDataChanged(useCallback(() => void reload(), [reload]));
  const status = useDataStatus();
  const pending = data?.counts.pending_drafts ?? 0;
  const { pathname } = useLocation();
  usePageMeta();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return (
    <div className="relative min-h-screen text-ink">
      <Suspense fallback={<div aria-hidden="true" className="fixed inset-0 z-0 bg-paper" />}>
        <World />
      </Suspense>
      <header className="no-print pointer-events-none fixed inset-x-0 top-0 z-30 px-3 pt-3 sm:px-5">
        <div className="pointer-events-auto mx-auto flex max-w-[1320px] flex-wrap items-center gap-x-5 gap-y-2 rounded-2xl bg-white/80 px-4 py-2 shadow-[0_10px_40px_-20px_rgba(15,20,30,0.35)] ring-1 ring-black/[0.05] backdrop-blur-xl">
          <Logo />
          <nav aria-label="Main" className="-mx-1 flex min-w-0 flex-1 gap-0.5 overflow-x-auto">
            {NAV.map(({ to, label, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => clsx("flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-[14px] transition-colors", isActive ? "bg-black/[0.06] font-medium text-ink" : "text-ink-3 hover:text-ink")}
              >
                {label}
                {to === "/approvals" && pending > 0 && <span className="num rounded-full bg-amber px-1.5 text-[12px] font-semibold leading-[18px] text-black">{pending}</span>}
              </NavLink>
            ))}
          </nav>
          <DataLabel />
          <div className="hidden shrink-0 md:block">
            <RunButton />
          </div>
        </div>
      </header>
      <main className="relative z-10">
        <Outlet />
      </main>
      <footer className="no-print relative z-10 px-4 pb-24 sm:px-8 md:pb-6">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center justify-between gap-2 rounded-2xl bg-white/75 px-5 py-3.5 text-[13px] text-ink-3 ring-1 ring-black/[0.05] backdrop-blur-xl">
          <span>
            {status?.mode === "real"
              ? "Your own accounts and notes. Leads are real companies, each with its source. The app cannot send email."
              : "Acme Cloud Security and its CRM are fictional. Leads are real public companies, each with a source link. The app cannot send email."}
          </span>
          <a href="https://github.com/umer-78" target="_blank" rel="noreferrer" className="font-medium text-ink hover:underline">
            Built by Umer Hashmi
          </a>
        </div>
      </footer>
      <div className="no-print fixed inset-x-0 bottom-0 z-40 bg-white/90 p-3 ring-1 ring-black/[0.05] backdrop-blur md:hidden">
        <RunButton className="w-full" />
      </div>
      <AccessGate />
    </div>
  );
}
