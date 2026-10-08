import { type ReactNode, useEffect, useRef, useState } from "react";
import { IconCheck, IconChevronDown } from "./icons";

export type Tone = "green" | "red" | "amber" | "slate" | "brand" | "violet" | "sky";

const tones: Record<Tone, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/15",
  red: "bg-rose-50 text-rose-700 ring-rose-600/15",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  slate: "bg-slate-100 text-slate-600 ring-slate-500/10",
  brand: "bg-brand-50 text-brand-700 ring-brand-600/15",
  violet: "bg-violet-50 text-violet-700 ring-violet-600/15",
  sky: "bg-sky-50 text-sky-700 ring-sky-600/15",
};

export function Badge({ tone = "slate", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function PassBadge({ passed, error }: { passed: boolean; error?: boolean }) {
  if (error) return <Badge tone="amber">Error</Badge>;
  return passed ? <Badge tone="green">Pass</Badge> : <Badge tone="red">Fail</Badge>;
}

const changeTone: Record<string, Tone> = {
  FIXED: "green", improved: "green", REGRESSED: "red", worse: "red", error: "amber", same: "slate",
};

export function ChangeBadge({ change }: { change: string }) {
  const label = change === "FIXED" ? "Fixed" : change === "REGRESSED" ? "Regressed" : change;
  return <Badge tone={changeTone[change] ?? "slate"}>{label}</Badge>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2.5">{actions}</div>}
    </div>
  );
}

export function Card({ title, right, children, className = "", bodyClassName = "p-5" }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <h2 className="text-[15px] font-semibold text-slate-800">{title}</h2>
          {right}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: boolean }) {
  return (
    <div className={`card px-5 py-4 ${accent ? "bg-gradient-to-br from-brand-600 to-brand-800 text-white ring-0" : ""}`}>
      <div className={`text-xs font-medium ${accent ? "text-brand-100" : "text-slate-500"}`}>{label}</div>
      <div className="mt-1 text-2xl font-bold tabular-nums tracking-tight">{value}</div>
      {sub && <div className={`mt-0.5 text-xs ${accent ? "text-brand-100" : "text-slate-400"}`}>{sub}</div>}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-xl bg-slate-100/80 p-1">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
                className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
                  value === t.id ? "bg-white text-brand-800 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>
          {t.label}
          {t.count !== undefined && <span className="ml-1.5 text-slate-400">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Closes a popover when clicking outside it. */
export function useOutsideClose(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);
  return ref;
}

/** Modern dropdown replacing the native <select>. */
export function Select<T extends string | number>({ value, options, onChange, className = "", icon }: {
  value: T; options: { value: T; label: string; hint?: string }[]; onChange: (v: T) => void;
  className?: string; icon?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(() => setOpen(false));
  const current = options.find((o) => o.value === value);
  return (
    <div ref={ref} className={`relative ${className}`}>
      <button type="button" onClick={() => setOpen((o) => !o)}
              className={`flex w-full items-center gap-2 rounded-xl bg-white px-3.5 py-2.5 text-sm font-medium text-slate-700 ring-1 transition hover:ring-brand-300 ${
                open ? "ring-2 ring-brand-500" : "ring-slate-200"}`}>
        {icon && <span className="text-slate-400">{icon}</span>}
        <span className="flex-1 truncate text-left">{current?.label ?? "Select"}</span>
        <IconChevronDown className={`h-4 w-4 text-slate-400 transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ul className="absolute right-0 z-30 mt-2 max-h-72 w-full min-w-[14rem] overflow-auto rounded-xl bg-white p-1.5 shadow-xl shadow-slate-900/10 ring-1 ring-slate-200">
          {options.map((o) => (
            <li key={String(o.value)}>
              <button type="button" onClick={() => { onChange(o.value); setOpen(false); }}
                      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-brand-50 ${
                        o.value === value ? "font-semibold text-brand-800" : "text-slate-700"}`}>
                <span className="flex-1">
                  {o.label}
                  {o.hint && <span className="block text-xs font-normal text-slate-400">{o.hint}</span>}
                </span>
                {o.value === value && <IconCheck className="h-4 w-4 text-brand-600" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** One dot per trial: green pass, red fail, amber infrastructure error. */
export function TrialDots({ trials }: { trials: { passed: boolean; status: string }[] }) {
  return (
    <span className="inline-flex gap-1">
      {trials.map((t, i) => (
        <span key={i} className={`h-2.5 w-2.5 rounded-full ${
          t.status === "error" ? "bg-amber-400" : t.passed ? "bg-brand-500" : "bg-rose-500"}`} />
      ))}
    </span>
  );
}

export function ScoreBar({ value }: { value: number }) {
  const color = value >= 0.75 ? "bg-brand-500" : value >= 0.4 ? "bg-amber-400" : "bg-rose-500";
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
        <span className={`block h-full ${color}`} style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="w-8 text-xs tabular-nums text-slate-500">{value.toFixed(2)}</span>
    </span>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800 ring-1 ring-rose-200">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-2xl border border-dashed border-slate-300/70 bg-white/40 p-8 text-center text-sm text-slate-400">{children}</div>;
}

export function Spinner() {
  return <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />;
}

export const pct = (x: number) => `${Math.round(x * 100)}%`;
export const shortDate = (iso: string) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
export const humanize = (id: string) => id.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
