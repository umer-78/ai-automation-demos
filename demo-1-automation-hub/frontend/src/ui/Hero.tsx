import { useEffect, useState } from "react";
import DecryptedText from "../components/DecryptedText";
import { ShimmerButton } from "../components/ShimmerButton";
import { prefersReducedMotion, useHub } from "../store";
import { day } from "../lib/format";

export function Hero() {
  const status = useHub((s) => s.status);
  const dash = useHub((s) => s.dashboard);
  const error = useHub((s) => s.error);
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), 4000);
    return () => clearTimeout(t);
  }, []);

  const alerts = dash?.alerts.length ?? 0;
  const line = status
    ? `${status.clients} clients on the books. Ad data through ${day(status.latest_data)}. ${
        alerts === 0 ? "No cost-per-conversion alerts" : alerts === 1 ? "One cost-per-conversion alert" : `${alerts} cost-per-conversion alerts`
      } this week.`
    : error
      ? "The hub isn't answering yet. Reload in a moment to try again."
      : slow
        ? "Waking the server. Free hosting sleeps when idle, so the first load can take about 30 seconds."
        : "Loading live data from the hub.";

  return (
    <section id="top" data-scene={0} aria-labelledby="top-title" className="hero">
      <div className="hero-inner">
        <h1 id="top-title" className="h1">
          <DecryptedText
            text="Client onboarding, ad reporting and site drafts that run on their own."
            animateOn="hover" hoverRadius={70} effect="flip" speed={40} maxIterations={8}
            characters="abcdefghijklmnopqrstuvwxyz" encryptedClassName="text-fjord/45"
          />
        </h1>
        <p className="hero-lede">
          Add a client and watch Airtable, Make, Claude, Supabase and Slack set them up. Further down: the daily ad report and
          its alert, a weekly summary written by Claude, and website drafts you can change one section at a time.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-x-7 gap-y-3">
          <ShimmerButton onClick={() => document.getElementById("onboarding")?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth" })}>
            Add a client
          </ShimmerButton>
          <a className="link" href="#reporting">See today's ad report</a>
        </div>
        <p className="hero-status" role="status">{line}</p>
      </div>
    </section>
  );
}
