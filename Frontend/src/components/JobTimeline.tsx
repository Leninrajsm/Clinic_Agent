import type { JobEvent } from "../types";
import { CompareTable } from "./CompareTable";
import { PolicyDiff } from "./PolicyDiff";
import { Badge, PassBadge, humanize } from "./ui";

/** Live view of an eval or loop job. Trial results are grouped under the run they belong to. */
export function JobTimeline({ events }: { events: JobEvent[] }) {
  const blocks: JobEvent[][] = [];
  for (const e of events) {
    if (e.type === "trial_done" && blocks.length && blocks[blocks.length - 1][0].type === "run_started") {
      blocks[blocks.length - 1].push(e);
    } else {
      blocks.push([e]);
    }
  }
  if (!events.length) return <div className="text-sm text-slate-400">Starting…</div>;
  return <div className="space-y-3">{blocks.map((b, i) => <EventBlock key={i} group={b} />)}</div>;
}

const note = "rounded-xl px-3 py-2 text-sm";

function EventBlock({ group }: { group: JobEvent[] }) {
  const e = group[0];
  switch (e.type) {
    case "run_started": {
      const trials = group.slice(1);
      const total = e.scenarios * e.trials;
      const passed = trials.filter((t) => t.passed).length;
      return (
        <div className="rounded-xl bg-slate-50 p-4 ring-1 ring-slate-200/70">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="font-medium text-slate-800">{humanize(e.label || "evaluation")} · policy {e.policy_version}</span>
            <span className="tabular-nums text-slate-500">{trials.length}/{total} conversations · {passed} passed</span>
          </div>
          <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-slate-200/70">
            <div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${(trials.length / total) * 100}%` }} />
          </div>
          <div className="mt-3 flex flex-wrap gap-1">
            {trials.map((t, k) => (
              <span key={k} title={`${humanize(t.scenario_id)} · trial ${t.trial} · score ${t.score}`}
                    className={`h-2.5 w-2.5 rounded-sm ${t.status === "error" ? "bg-amber-400" : t.passed ? "bg-emerald-500" : "bg-rose-500"}`} />
            ))}
          </div>
        </div>
      );
    }
    case "run_finished":
      return (
        <div className={`${note} bg-brand-50 text-brand-900`}>
          Finished: <b>{e.summary.overall.passed}/{e.summary.overall.total}</b> scenarios passed · train{" "}
          {e.summary.train.passed}/{e.summary.train.total} · holdout {e.summary.holdout.passed}/{e.summary.holdout.total}
        </div>
      );
    case "baseline_reused":
      return <div className={`${note} bg-slate-50 text-slate-600`}>Reusing a saved baseline run.</div>;
    case "iteration_started":
      return (
        <div className="flex flex-wrap items-center gap-1.5 text-sm text-slate-700">
          Failing train scenarios:
          {e.failing_train.length ? e.failing_train.map((s: string) => <Badge key={s} tone="red">{humanize(s)}</Badge>) : " none"}
        </div>
      );
    case "analyzing":
      return <div className={`${note} bg-violet-50 text-violet-800`}>Analyzer is reading the failures (attempt {e.attempt})…</div>;
    case "proposals":
      return (
        <div className="space-y-2">
          {e.proposals.map((p: any, k: number) => (
            <div key={k} className="rounded-xl bg-violet-50/60 p-3 ring-1 ring-violet-100">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-violet-500">Diagnosis · {p.failure_cluster}</div>
              <div className="mt-0.5 text-sm text-slate-800">{p.root_cause}</div>
            </div>
          ))}
          {e.code_tickets.map((p: any, k: number) => (
            <div key={`t${k}`} className={`${note} bg-amber-50 text-amber-900`}>Needs a code change: {p.code_change_ticket}</div>
          ))}
        </div>
      );
    case "candidate_created":
      return (
        <div>
          <div className="mb-1.5 text-sm font-medium text-slate-700">Candidate policy {e.version}</div>
          <PolicyDiff diff={e.diff} />
          {e.rejected?.map((r: string) => <div key={r} className="mt-1 text-xs text-amber-700">Refused edit: {r}</div>)}
        </div>
      );
    case "rechecking":
      return <div className={`${note} bg-amber-50 text-amber-900`}>Possible regressions found; re-running them to rule out noise…</div>;
    case "gate":
      return (
        <div className={`rounded-xl p-4 ring-1 ${e.accepted ? "bg-emerald-50/60 ring-emerald-200" : "bg-rose-50/60 ring-rose-200"}`}>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
            Regression gate · {e.version} <PassBadge passed={e.accepted} />
          </div>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {Object.entries(e.rules as Record<string, boolean>).map(([k, v]) => (
              <Badge key={k} tone={v ? "green" : "red"}>{v ? "✓" : "✗"} {k.replaceAll("_", " ")}</Badge>
            ))}
          </div>
          <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200/70">
            <CompareTable rows={e.table} before="before" after="after" />
          </div>
        </div>
      );
    case "awaiting_review":
      return (
        <div className={`${note} bg-amber-50 text-amber-900 ring-1 ring-amber-200`}>
          <b>{e.version}</b> passed the gate and is waiting for your approval on the Policies page. {e.active} stays live.
        </div>
      );
    case "analyzer_fallback":
      return <div className={`${note} bg-amber-50 text-amber-800`}>Analyzer {e.from} unavailable; using {e.to}.</div>;
    case "attempt_failed":
      return <div className={`${note} bg-amber-50 text-amber-800`}>Attempt failed: {e.reason}</div>;
    case "loop_finished":
      return <div className="rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white">{String(e.outcome).split(". Approve")[0]}</div>;
    case "job_error":
      return <div className={`${note} bg-rose-50 text-rose-800`}>Job failed: {e.error}</div>;
    default:
      return null;
  }
}
