import clsx from "clsx";
import type { ReactNode } from "react";
import { useSectionShot, type Shot, type ShotName } from "./store";

/**
 * One screen of a page. When it reaches the middle of the viewport the camera flies to its shot;
 * the panel floats on the side the shot leaves free.
 */
export function Section({ shot, focus = null, side = "left", wide = false, className, children }: { shot: ShotName; focus?: Shot | null; side?: "left" | "right"; wide?: boolean | "xl"; className?: string; children: ReactNode }) {
  const ref = useSectionShot<HTMLElement>(shot, focus);
  return (
    <section ref={ref} className={clsx("pointer-events-none flex min-h-[100svh] px-4 pb-14 pt-28 sm:px-8 max-[899px]:items-end min-[900px]:items-center", className)}>
      <div className={clsx("mx-auto flex w-full max-w-[1320px]", side === "right" ? "justify-end" : "justify-start")}>
        <div className={clsx("pointer-events-auto w-full", wide === "xl" ? "max-w-[960px]" : wide ? "max-w-[640px]" : "max-w-[500px]")}>{children}</div>
      </div>
    </section>
  );
}

export function Card({ children, className, tone = "white" }: { children: ReactNode; className?: string; tone?: "white" | "alert" }) {
  return (
    <div
      className={clsx(
        "rounded-[22px] p-6 shadow-[0_30px_80px_-40px_rgba(15,20,30,0.45)] ring-1 backdrop-blur-xl sm:p-7",
        tone === "alert" ? "bg-[#fef5f4]/[0.97] ring-[#e5484d]/15" : "bg-white/[0.96] ring-black/[0.05]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h2 className="text-[24px] font-semibold leading-tight tracking-[-0.025em]">{children}</h2>
      {aside && <div className="text-[13.5px] text-[#5B616B]">{aside}</div>}
    </div>
  );
}

export const btn = {
  primary: "inline-flex min-h-11 items-center justify-center gap-2 rounded-[11px] bg-black px-[18px] text-[15px] font-medium text-white transition-colors hover:bg-[#23272e] disabled:opacity-50",
  secondary: "inline-flex min-h-11 items-center justify-center gap-2 rounded-[11px] bg-white px-[18px] text-[15px] font-medium text-black ring-1 ring-black/[0.12] transition hover:ring-black/40 disabled:opacity-50",
  quiet: "inline-flex min-h-11 items-center justify-center gap-2 rounded-[11px] px-3 text-[15px] font-medium transition-colors hover:bg-black/[0.05] disabled:opacity-50",
};

/** The first card of a long page: its title, what it is for, and its actions. */
export function PageIntro({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.03em]">{title}</h1>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {description && <p className="mt-2 max-w-[62ch] text-[15px] leading-relaxed text-ink-2">{description}</p>}
    </Card>
  );
}
