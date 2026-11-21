import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from "lucide-react";
import { AnimatePresence, motion, useMotionTemplate, useSpring, useTransform } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useState, type ButtonHTMLAttributes, type PointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { ScoreParts } from "../lib/api";
import { FLAG_LABEL } from "../lib/format";
import { usePrefersReducedMotion } from "../lib/hooks";

// ------------------------------------------------------------------ button
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "signal" | "dark" | "secondary" | "ghost" | "danger" | "approve";
  size?: "sm" | "md" | "lg";
  busy?: boolean;
  icon?: ReactNode;
};

export function Button({ variant = "secondary", size = "md", busy, icon, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-55",
        size === "sm" && "h-8 px-3 text-[13px]",
        size === "md" && "h-10 px-4 text-[14px]",
        size === "lg" && "h-12 px-6 text-[16px]",
        variant === "signal" && "bg-amber text-spruce hover:bg-[#f0b052]",
        variant === "dark" && "bg-spruce text-sheet hover:bg-spruce-2",
        variant === "secondary" && "border border-rule bg-sheet text-ink hover:border-ink-3/50",
        variant === "ghost" && "text-ink-2 hover:bg-spruce/5 hover:text-ink",
        variant === "danger" && "border border-crimson/30 bg-crimson-soft text-crimson hover:border-crimson/60",
        variant === "approve" && "bg-moss text-sheet hover:bg-[#356b53]",
        className,
      )}
    >
      {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ layout bits
export function Panel({ title, action, children, className, padded = true, subtitle }: { title?: ReactNode; subtitle?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <section className={clsx("panel", className)}>
      {(title || action) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule-soft px-5 py-3.5">
          <div>
            <h2 className="heading text-[16px]">{title}</h2>
            {subtitle && <p className="text-[13px] text-ink-3">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={padded ? "p-5" : undefined}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="display text-[34px] md:text-[44px]">{title}</h1>
        {description && <p className="mt-3 text-[16px] text-ink-2">{description}</p>}
      </div>
      {actions && <div className="no-print flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

const chipTone = {
  amber: "bg-amber-soft text-amber-ink",
  moss: "bg-moss-soft text-moss",
  crimson: "bg-crimson-soft text-crimson",
  sage: "bg-sage-soft text-spruce-3",
  neutral: "bg-spruce/[0.06] text-ink-2",
  cobalt: "bg-[#e6ecf8] text-cobalt",
};
export type Tone = keyof typeof chipTone;

export function Chip({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[12.5px] font-semibold", chipTone[tone], className)}>
      {children}
    </span>
  );
}

const STATUS: Record<string, [Tone, string]> = {
  pending: ["amber", "Waiting for approval"],
  approved: ["moss", "Approved, ready to send"],
  edited: ["moss", "Edited and approved"],
  rejected: ["crimson", "Rejected"],
  sent: ["cobalt", "Sent by a person"],
  new: ["sage", "New"],
  drafted: ["amber", "Draft in queue"],
  contacted: ["cobalt", "Contacted"],
  excluded: ["neutral", "Excluded"],
  running: ["amber", "Running"],
  completed: ["moss", "Completed"],
  completed_with_fallback: ["sage", "Completed with fallback"],
  failed: ["crimson", "Failed"],
  success: ["moss", "Success"],
  failure: ["crimson", "Failure"],
  simulated: ["neutral", "Simulated"],
};

export function StatusChip({ status }: { status: string }) {
  const [tone, label] = STATUS[status] ?? ["neutral", status];
  return <Chip tone={tone}>{label}</Chip>;
}

export function FlagChip({ flag }: { flag: string }) {
  const tone: Tone = flag === "upsell" ? "moss" : flag === "stalled" ? "amber" : "crimson";
  return <Chip tone={tone}>{FLAG_LABEL[flag] ?? flag}</Chip>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-spruce/[0.07]", className)} />;
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-rule px-6 py-10 text-center">
      <p className="heading text-[16px]">{title}</p>
      {children && <div className="mx-auto mt-1.5 max-w-md text-[14px] text-ink-2">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-crimson/30 bg-crimson-soft px-4 py-3 text-[14px] text-crimson">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}

export function Tabs<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string; count?: number }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1 border-b border-rule">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "-mb-px border-b-2 px-3 py-2 text-[14px] font-semibold transition-colors",
            o.value === value ? "border-amber text-ink" : "border-transparent text-ink-3 hover:text-ink",
          )}
        >
          {o.label}
          {o.count !== undefined && (
            <>
              {" "}
              <span className="num ml-1 text-ink-3">{o.count}</span>
            </>
          )}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ score anatomy
/** One bar, three segments: fit (out of 50), buying signals (30) and recency (20). */
export function ScoreBar({ parts, score, size = "md", dimmed }: { parts: ScoreParts | null | undefined; score: number; size?: "sm" | "md"; dimmed?: boolean }) {
  const p = parts ?? { fit: score, signals: 0, recency: 0 };
  const total = p.fit + p.signals + p.recency;
  const capped = score < total; // excluded leads are capped; show the raw parts faded
  return (
    <div className={clsx("flex items-center gap-2.5", dimmed && "opacity-50")}>
      <span className={clsx("num w-8 text-right font-bold", size === "sm" ? "text-[14px]" : "text-[17px]")}>{score}</span>
      <div
        className={clsx("flex flex-1 overflow-hidden rounded-full bg-spruce/[0.07]", size === "sm" ? "h-1.5" : "h-2.5", capped && "opacity-40")}
        role="img"
        aria-label={`Score ${score} of 100: fit ${p.fit} of 50, signals ${p.signals} of 30, recency ${p.recency} of 20`}
      >
        <span style={{ width: `${p.fit}%` }} className="bg-spruce" />
        <span style={{ width: `${p.signals}%` }} className="bg-amber" />
        <span style={{ width: `${p.recency}%` }} className="bg-sage" />
      </div>
    </div>
  );
}

export function ScoreLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink-3">
      <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-full bg-spruce" /> Fit, up to 50</span>
      <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-full bg-amber" /> Buying signals, up to 30</span>
      <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-full bg-sage" /> Recency, up to 20</span>
    </div>
  );
}

// ------------------------------------------------------------------ drawer
export function Drawer({ open, onClose, title, children, width = 640 }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: number }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50">
          <motion.div className="absolute inset-0 bg-spruce/35" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside
            role="dialog"
            aria-modal="true"
            className="absolute right-0 top-0 flex h-full w-full flex-col bg-paper shadow-2xl"
            style={{ maxWidth: width }}
            initial={{ x: 40, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 40, opacity: 0 }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
          >
            <header className="flex items-start justify-between gap-4 border-b border-rule bg-sheet px-6 py-4">
              <div className="min-w-0">{title}</div>
              <button onClick={onClose} className="rounded-md p-1.5 text-ink-3 hover:bg-spruce/5 hover:text-ink" aria-label="Close">
                <X className="size-5" />
              </button>
            </header>
            <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
          </motion.aside>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

// ------------------------------------------------------------------ 3D surfaces
/**
 * A sheet of paper you can tip with the mouse: it tilts toward the pointer and its shadow moves
 * the other way. Touch input and reduced-motion users get a still sheet.
 */
export function Tilt({ children, className, max = 3, disabled }: { children: ReactNode; className?: string; max?: number; disabled?: boolean }) {
  const reduced = usePrefersReducedMotion();
  const off = reduced || disabled;
  const rx = useSpring(0, { stiffness: 180, damping: 22 });
  const ry = useSpring(0, { stiffness: 180, damping: 22 });
  const sx = useTransform(ry, (v) => -v * 3);
  const sy = useTransform(rx, (v) => 22 + v * 3);
  const shadow = useMotionTemplate`${sx}px ${sy}px 44px -26px rgba(15, 59, 53, 0.42)`;
  useEffect(() => {
    if (off) {
      rx.set(0);
      ry.set(0);
    }
  }, [off, rx, ry]);
  const move = (e: PointerEvent<HTMLDivElement>) => {
    if (off || e.pointerType !== "mouse") return;
    const r = e.currentTarget.getBoundingClientRect();
    ry.set(((e.clientX - r.left) / r.width - 0.5) * 2 * max);
    rx.set(-((e.clientY - r.top) / r.height - 0.5) * 2 * max);
  };
  const leave = () => {
    rx.set(0);
    ry.set(0);
  };
  return (
    <motion.div
      onPointerMove={move}
      onPointerLeave={leave}
      className={clsx("rounded-[6px]", className)}
      style={off ? undefined : { rotateX: rx, rotateY: ry, transformPerspective: 1400, boxShadow: shadow }}
    >
      {children}
    </motion.div>
  );
}

const STAMP = {
  approved: { label: "Approved", tone: "border-moss text-moss" },
  sent: { label: "Sent", tone: "border-cobalt text-cobalt" },
  returned: { label: "Returned", tone: "border-crimson text-crimson" },
} as const;

/**
 * A rubber stamp on the draft. It lands with a press (scale down, tip flat) when the reviewer acts,
 * and sits still when the page simply opens an already reviewed draft.
 */
export function Stamp({ kind, note, press }: { kind: keyof typeof STAMP; note?: string | null; press: boolean }) {
  const s = STAMP[kind];
  return (
    <motion.div
      aria-hidden
      className={clsx("pointer-events-none absolute right-4 top-3 z-10 max-w-[220px] select-none rounded-md border-[3px] px-3 py-1 text-center mix-blend-multiply", s.tone)}
      style={{ rotate: -7, transformPerspective: 500 }}
      initial={press ? { scale: 2.1, opacity: 0, rotateX: 34, rotateY: -14, y: -18 } : false}
      animate={{ scale: 1, opacity: 0.9, rotateX: 0, rotateY: 0, y: 0 }}
      transition={{ type: "spring", stiffness: 560, damping: 24, mass: 0.8 }}
    >
      <div className="rounded-sm border border-current px-2 py-0.5 text-[20px] font-extrabold uppercase leading-tight tracking-[0.14em]">{s.label}</div>
      {note && <div className="mt-1 line-clamp-2 text-[11.5px] font-semibold leading-snug">{note}</div>}
    </motion.div>
  );
}

// ------------------------------------------------------------------ toasts
type Toast = { id: number; tone: "success" | "error" | "info"; text: string };
const ToastCtx = createContext<(tone: Toast["tone"], text: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, text }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-5 right-5 z-[60] flex w-[min(380px,calc(100vw-2.5rem))] flex-col gap-2">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              className="pointer-events-auto flex items-start gap-2.5 rounded-xl bg-spruce px-4 py-3 text-[14px] text-sheet shadow-xl"
            >
              {t.tone === "success" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-sage" /> : t.tone === "error" ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber" /> : <Info className="mt-0.5 size-4 shrink-0 text-sage" />}
              <span>{t.text}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
