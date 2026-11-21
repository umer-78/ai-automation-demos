import { useEffect, useState } from "react";
import { ShimmerButton } from "../components/ShimmerButton";
import { useAgent } from "../store";
import { day } from "../lib/format";
import { goTo, startRun } from "../actions";

export function Hero() {
  const status = useAgent((s) => s.status);
  const error = useAgent((s) => s.error);
  const running = useAgent((s) => !!s.live && !s.live.done);
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), 4000);
    return () => clearTimeout(t);
  }, []);

  const c = status?.counts;
  const line = status && c
    ? `${c.leads} leads scored so far, ${c.waiting} ${c.waiting === 1 ? "email" : "emails"} waiting for approval, ${c.accounts} CRM accounts checked. ${
        status.live_search ? "Research runs on live web search." : `Research comes from real web results saved on ${day(status.snapshot_date)}.`
      }`
    : error
      ? "The agent's server isn't answering yet. Reload in a moment to try again."
      : slow
        ? "Waking the server. Free hosting sleeps when idle, so the first load can take about 30 seconds."
        : "Loading the agent's latest work.";

  return (
    <section id="top" data-scene={0} aria-labelledby="top-title" className="hero">
      <div className="hero-inner">
        <h1 id="top-title" className="h1">Your next leads, researched and written to. Nothing goes out until you approve it.</h1>
        <p className="hero-lede">
          The agent reads Acme's notes and past deals, finds companies showing buying signals, scores each one, checks every CRM
          account for stalled deals, and drafts emails that cite a real, linked fact. You approve, edit or reject each draft, and
          your reasons shape the next run.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-x-7 gap-y-3">
          <ShimmerButton disabled={running} onClick={() => { goTo("run"); if (!running) void startRun(); }}>
            {running ? "The agent is running" : "Run the agent"}
          </ShimmerButton>
          <a className="link" href="#queue">Review the drafts</a>
        </div>
        <p className="hero-status" role="status">{line}</p>
      </div>
    </section>
  );
}
