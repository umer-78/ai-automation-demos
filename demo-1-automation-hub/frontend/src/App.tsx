import { lazy, Suspense, useEffect, useMemo } from "react";
import { MotionConfig } from "motion/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { hub, scroll, useHub } from "./store";
import { refreshAll, useBoot } from "./data";
import { TopBar } from "./ui/TopBar";
import { Hero } from "./ui/Hero";
import { Onboarding } from "./ui/Onboarding";
import { Reporting } from "./ui/Reporting";
import { SiteBuilder } from "./ui/SiteBuilder";
import { Ops } from "./ui/Ops";

gsap.registerPlugin(ScrollTrigger);

// three.js loads after the page is readable, so text paints first.
const Scene = lazy(() => import("./scene/Scene"));

function hasWebGL() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") ?? c.getContext("webgl"));
  } catch {
    return false;
  }
}

/** Tracks which section is on screen; the 3D camera follows. */
function useScrollSections() {
  useEffect(() => {
    const sections = Array.from(document.querySelectorAll<HTMLElement>("[data-scene]"));
    const triggers = sections.map((el, i) =>
      ScrollTrigger.create({
        trigger: el,
        start: "top center",
        end: "bottom center",
        onUpdate: (self) => { scroll.progress = i + self.progress; },
        onToggle: (self) => { if (self.isActive && hub.get().section !== i) hub.set({ section: i }); },
      }),
    );
    triggers.forEach((t, i) => {
      if (t.isActive) { scroll.progress = i + t.progress; hub.set({ section: i }); }
    });
    // Panels grow as results arrive; keep the trigger positions in step.
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => ScrollTrigger.refresh());
    });
    const main = document.querySelector("main");
    if (main) observer.observe(main);
    return () => { triggers.forEach((t) => t.kill()); observer.disconnect(); cancelAnimationFrame(frame); };
  }, []);
}

function ErrorBanner() {
  const error = useHub((s) => s.error);
  if (!error) return null;
  return (
    <div role="alert" className="banner">
      <b>The hub isn't answering.</b> {error}. Free hosting puts the server to sleep when it's idle, so the first request can take
      about 30 seconds. <button type="button" className="link" onClick={() => void refreshAll()}>Try again</button>
    </div>
  );
}

export default function App() {
  useBoot();
  useScrollSections();
  const webgl = useMemo(hasWebGL, []);
  return (
    <MotionConfig reducedMotion="user">
      <div className="scene-layer" aria-hidden="true">
        {webgl ? (
          <>
            <Suspense fallback={null}><Scene /></Suspense>
            <div id="screen-layer" className="screen-layer" />
          </>
        ) : (
          <p className="no-webgl">This browser can't show the 3D view. Everything on the page still works.</p>
        )}
      </div>
      <a href="#onboarding" className="skip">Skip to the demo</a>
      <TopBar />
      <ErrorBanner />
      <main>
        <Hero />
        <Onboarding />
        <Reporting />
        <SiteBuilder />
        <Ops />
      </main>
    </MotionConfig>
  );
}
