import clsx from "clsx";
import { Suspense, lazy, useEffect, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { accessCode, isLocked, onLockChange, setAccessCode } from "../lib/api";
import { timeAgo } from "../lib/format";
import { useStatus, useSyncStatus } from "../lib/hooks";
import { usePageMeta } from "../lib/seo";
// the 3D world (three.js) loads after the page text, so words and numbers paint first
const World = lazy(() => import("../world/World"));

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/clients", label: "Clients" },
  { to: "/reporting", label: "Reporting" },
  { to: "/automations", label: "Automation" },
  { to: "/sites", label: "Sites" },
  { to: "/settings", label: "Settings" },
];

/** Where the numbers on screen come from, and how fresh they are. */
function LiveStatus() {
  const status = useStatus();
  const { lastSync, failed } = useSyncStatus();
  const d = status?.data;
  const ago = lastSync ? Math.max(0, Math.round((Date.now() - lastSync) / 1000)) : null;
  const stale = failed || ago === null || ago > 90;
  const label = failed ? "Reconnecting" : (d?.label ?? "Connecting");
  const detail = failed ? null : d?.mode === "real" && d.last_sync ? `synced ${timeAgo(d.last_sync.at)}` : d?.mode === "real" && d.last_import ? `imported ${timeAgo(d.last_import.at)}` : ago !== null ? (ago < 5 ? "just now" : `${ago}s ago`) : null;
  const title = !d ? "" : d.mode === "demo" ? "Sample clients. Their numbers follow published 2026 industry medians." : d.live_sources.length ? `Pulled from ${d.live_sources.join(", ")}` : "From your imported files";
  return (
    <div className="hidden items-center gap-2 text-[13.5px] text-[#5B616B] md:flex" title={title}>
      {stale ? <span className="size-2 rounded-full bg-[#b9bec7]" /> : d?.mode === "demo" ? <span className="size-2 rounded-full bg-[#f5a524]" /> : <span className="live-dot" />}
      <span className="font-medium text-black">{label}</span>
      {detail && <span className="num">{detail}</span>}
    </div>
  );
}

/** Real client data needs the owner's (or a teammate's) access code before anything loads. */
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
    <div role="dialog" aria-modal="true" aria-labelledby="gate-title" className="fixed inset-0 z-50 grid place-items-center bg-[#eef0f3]/80 px-4 backdrop-blur-md">
      <form onSubmit={open} className="w-full max-w-[420px] rounded-[22px] bg-white p-7 shadow-[0_30px_80px_-40px_rgba(15,20,30,0.45)] ring-1 ring-black/[0.06]">
        <h2 id="gate-title" className="text-[22px] font-semibold tracking-[-0.02em]">Real client data</h2>
        <p className="mt-2 text-[15px] leading-relaxed text-[#3f444c]">This hub runs on real numbers from your clients' accounts. Enter the access code to open it.</p>
        <input autoFocus type="password" autoComplete="current-password" className="field mt-4 w-full" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Access code" aria-label="Access code" />
        {tried && <p className="mt-2 text-[13.5px] text-[#B42318]">That code did not open the hub. Check it with the owner.</p>}
        <button type="submit" disabled={!code.trim()} className="mt-4 inline-flex min-h-11 w-full items-center justify-center rounded-[11px] bg-black px-[18px] text-[15px] font-medium text-white disabled:opacity-50">
          Open the hub
        </button>
      </form>
    </div>
  );
}

export default function Layout() {
  const { pathname } = useLocation();
  const status = useStatus();
  usePageMeta();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return (
    <div className="relative min-h-screen text-black">
      <Suspense fallback={<div aria-hidden="true" className="fixed inset-0 z-0 bg-[#eef0f3]" />}>
        <World />
      </Suspense>
      <header className="pointer-events-none fixed inset-x-0 top-0 z-30 px-3 pt-3 sm:px-5">
        <div className="pointer-events-auto mx-auto flex max-w-[1320px] flex-wrap items-center gap-x-6 gap-y-2 rounded-2xl bg-white/80 px-4 py-2 shadow-[0_10px_40px_-20px_rgba(15,20,30,0.35)] ring-1 ring-black/[0.05] backdrop-blur-xl">
          <NavLink to="/" className="flex items-center gap-2.5 text-[17px] font-bold tracking-[-0.02em]">
            <span aria-hidden="true" className="inline-block size-[18px] rounded-[5px] bg-black" />
            Northwind
          </NavLink>
          <nav aria-label="Main" className="-mx-1 flex min-w-0 flex-1 gap-0.5 overflow-x-auto">
            {NAV.map(({ to, label, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => clsx("shrink-0 rounded-lg px-3 py-2 text-[14.5px] transition-colors", isActive ? "bg-black/[0.06] font-medium text-black" : "text-[#5B616B] hover:text-black")}
              >
                {label}
              </NavLink>
            ))}
          </nav>
          <LiveStatus />
        </div>
      </header>
      <main className="relative z-10">
        <Outlet />
      </main>
      <AccessGate />
      <footer className="relative z-10 px-4 pb-6 sm:px-8">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center justify-between gap-2 rounded-2xl bg-white/75 px-5 py-3.5 text-[13px] text-[#5B616B] ring-1 ring-black/[0.05] backdrop-blur-xl">
          <span>
            {status?.data.mode === "real"
              ? "Every figure comes from your imported files and connected ad accounts. Nothing is estimated."
              : "Demo agency: sample clients whose numbers follow published 2026 industry medians. Load your own data in Settings."}
          </span>
          <a href="https://github.com/umer-78" target="_blank" rel="noreferrer" className="font-medium text-black hover:underline">
            Built by Umer Hashmi
          </a>
        </div>
      </footer>
    </div>
  );
}
