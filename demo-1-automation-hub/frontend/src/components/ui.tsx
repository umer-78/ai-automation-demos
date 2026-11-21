import clsx from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { X, Loader2, CheckCircle2, AlertTriangle, Info } from "lucide-react";
import { createContext, useRef, useCallback, useContext, useEffect, useState, type ReactNode, type ButtonHTMLAttributes } from "react";

// ------------------------------------------------------------------ button
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  busy?: boolean;
  icon?: ReactNode;
};

export function Button({ variant = "secondary", size = "md", busy, icon, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-10 px-4 text-[14px]",
        variant === "primary" && "bg-ink text-white hover:bg-ink/85",
        variant === "secondary" && "border border-edge bg-surface text-ink hover:border-ink/30",
        variant === "ghost" && "text-slate hover:bg-ink/[0.06] hover:text-ink",
        variant === "danger" && "border border-ember/30 bg-ember-soft text-ember-ink hover:border-ember/60",
        className,
      )}
    >
      {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ layout bits
export function Panel({ title, action, children, className, padded = true }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <section className={clsx("panel", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-edge px-5 py-3.5">
          <h2 className="heading text-[15px]">{title}</h2>
          {action}
        </header>
      )}
      <div className={padded ? "p-5" : undefined}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="display text-[30px] md:text-[36px]">{title}</h1>
        {description && <p className="mt-2 text-slate">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

const pillTone = {
  success: "bg-aurora-soft text-aurora-ink",
  failure: "bg-ember-soft text-ember-ink",
  warning: "bg-amber-soft text-amber",
  info: "bg-glacier-soft text-glacier",
  neutral: "bg-ink/[0.06] text-slate",
};

export function Pill({ tone = "neutral", children, className }: { tone?: keyof typeof pillTone; children: ReactNode; className?: string }) {
  return <span className={clsx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12.5px] font-medium", pillTone[tone], className)}>{children}</span>;
}

export const statusTone = (status: string): keyof typeof pillTone =>
  ({ active: "success", success: "success", sent: "success", onboarding: "info", new: "info", simulated: "neutral", churned: "warning", archived: "neutral", failure: "failure", failed: "failure", running: "info" })[status] as keyof typeof pillTone ?? "neutral";

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-ink/[0.07]", className)} />;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-edge px-6 py-10 text-center">
      <p className="heading text-[15px]">{title}</p>
      {children && <div className="mt-1.5 text-[14px] text-slate">{children}</div>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-ember/30 bg-ember-soft px-4 py-3 text-[14px] text-ember-ink">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-edge bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
            o.value === value ? "bg-surface text-ink shadow-[0_1px_2px_rgb(0_0_0/0.08),0_0_0_1px_rgb(0_0_0/0.06)]" : "text-slate hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ drawer
export function Drawer({ open, onClose, title, children, width = 520 }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: number }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}>
          <motion.div className="absolute inset-0 bg-black/55 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside
            className="absolute right-0 top-0 flex h-full w-full flex-col bg-surface shadow-2xl"
            style={{ maxWidth: width }}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 38 }}
          >
            <header className="flex items-center justify-between border-b border-edge px-6 py-4">
              <h2 className="heading text-[17px]">{title}</h2>
              <button onClick={onClose} className="rounded-md p-1.5 text-slate hover:bg-ink/[0.06] hover:text-ink" aria-label="Close">
                <X className="size-5" />
              </button>
            </header>
            <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
          </motion.aside>
        </div>
      )}
    </AnimatePresence>
  );
}

// ------------------------------------------------------------------ toasts
type Toast = { id: number; tone: "success" | "failure" | "info"; text: string };
const ToastCtx = createContext<(tone: Toast["tone"], text: string) => void>(() => undefined);
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, text }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5200);
  }, []);
  const Icon = { success: CheckCircle2, failure: AlertTriangle, info: Info };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[60] flex w-[360px] max-w-[calc(100vw-2.5rem)] flex-col gap-2" aria-live="polite">
        <AnimatePresence>
          {toasts.map((t) => {
            const I = Icon[t.tone];
            return (
              <motion.div
                key={t.id}
                layout
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: 40 }}
                className="pointer-events-auto flex items-start gap-3 rounded-lg border border-edge bg-surface px-4 py-3 text-[14px] shadow-lg"
              >
                <I className={clsx("mt-0.5 size-4 shrink-0", t.tone === "success" && "text-aurora-ink", t.tone === "failure" && "text-ember", t.tone === "info" && "text-glacier")} />
                <span>{t.text}</span>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

export function Field({ label, hint, children, error }: { label: string; hint?: string; children: ReactNode; error?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13.5px] font-medium">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-[12.5px] text-slate">{hint}</span>}
      {error && <span className="mt-1 block text-[12.5px] text-ember-ink">{error}</span>}
    </label>
  );
}

/** A number that counts to its new value when live data changes it. */
export function AnimatedNumber({ value, format = (n: number) => Math.round(n).toLocaleString("en-US") }: { value: number; format?: (n: number) => string }) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const start = performance.now();
    const a = from.current;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || a === value) {
      from.current = value;
      setShown(value);
      return;
    }
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / 700);
      const eased = 1 - Math.pow(1 - k, 3);
      setShown(a + (value - a) * eased);
      if (k < 1) raf = requestAnimationFrame(step);
      else from.current = value;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{format(shown)}</>;
}
