import { useCallback, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { BorderBeam } from "../components/BorderBeam";
import { cn } from "../lib/cn";

/** A scroll stop. The 3D camera holds one shot while its section is on screen. */
export function Section({ id, scene, children }: { id: string; scene: number; children: ReactNode }) {
  return (
    <section id={id} data-scene={scene} aria-labelledby={`${id}-title`} className="stop">
      {children}
    </section>
  );
}

/** The single surface for a section. Content inside is divided by hairlines, never by nested cards. */
export function Panel({ id, title, intro, busy, children }: { id: string; title: string; intro: ReactNode; busy?: boolean; children: ReactNode }) {
  return (
    <div className="panel" aria-busy={busy || undefined}>
      {busy && <BorderBeam size={120} duration={3.2} borderWidth={2} />}
      <h2 id={`${id}-title`} className="h2">{title}</h2>
      <p className="lede">{intro}</p>
      {children}
    </div>
  );
}

/** A titled part of a panel, separated from what comes before by a hairline. */
export function Part({ title, children, foot, className }: { title: string; children: ReactNode; foot?: ReactNode; className?: string }) {
  return (
    <div className={cn("part", className)}>
      <h3 className="h3">{title}</h3>
      {children}
      {foot && <p className="small mt-2">{foot}</p>}
    </div>
  );
}

type Variant = "primary" | "secondary" | "danger" | "quiet";
export function Button({ variant = "primary", busy, disabled, type = "button", className, children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button type={type} {...rest} disabled={busy || disabled} aria-busy={busy || undefined} className={cn("btn", `btn-${variant}`, className)}>
      {busy && <span className="spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("field", className)}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export const Input = ({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cn("input", className)} />;
export const Select = ({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cn("input select", className)} />;
export const TextArea = ({ className, ...p }: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cn("input", className)} />;

export function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div role="radiogroup" aria-label={label} className="seg">
      {options.map(([v, text]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} className={cn("seg-item", value === v && "is-on")} onClick={() => onChange(v)}>
          {text}
        </button>
      ))}
    </div>
  );
}

const BADGES: Record<string, [string, string]> = {
  ok: ["Done", "ok"], success: ["Done", "ok"], failure: ["Failed", "bad"], saved: ["Draft saved", "info"], skipped: ["Skipped", "muted"],
  failed: ["Failed", "bad"], error: ["Failed", "bad"], alert: ["Alert", "warn"],
};
export function StatusBadge({ status }: { status: string }) {
  const [text, tone] = BADGES[status] ?? [status, "muted"];
  return <span className={`badge badge-${tone}`}>{text}</span>;
}

export function ErrorNote({ error }: { error: string | null }) {
  return error ? <p role="alert" className="note note-bad">{error}</p> : null;
}

export function Note({ children }: { children: ReactNode }) {
  return <p role="status" className="note">{children}</p>;
}

/** Runs one async action at a time and keeps its busy and error state. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(key);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      setBusy(null);
    }
  }, []);
  return { busy, error, setError, run };
}
