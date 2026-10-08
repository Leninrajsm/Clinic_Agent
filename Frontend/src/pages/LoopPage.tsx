import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { CompareTable } from "../components/CompareTable";
import { IconAlert, IconChevron, IconPlay, IconSpark } from "../components/icons";
import { JobTimeline } from "../components/JobTimeline";
import { PolicyDiff } from "../components/PolicyDiff";
import { Badge, Card, Empty, ErrorNote, PageHeader, PassBadge, Select, Spinner, shortDate } from "../components/ui";
import { useJob } from "../hooks/useJob";
import type { LoopReport } from "../types";
import { TRIAL_OPTIONS } from "./EvalsPage";

const PIPELINE = ["Evaluate live policy", "Analyse train failures", "Write candidate policy", "Re-evaluate", "Regression gate"];

export default function LoopPage() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const loops = useQuery({ queryKey: ["loops"], queryFn: api.loops });
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const policies = useQuery({ queryKey: ["policies"], queryFn: api.policies });
  const loopId = params.get("loop") ?? loops.data?.[0]?.loop_id ?? null;

  const [trials, setTrials] = useState(3);
  const [attempts, setAttempts] = useState(2);
  const [baseline, setBaseline] = useState("");
  const [review, setReview] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);

  const start = useMutation({
    mutationFn: () => api.startLoop({ trials, max_attempts: attempts, baseline_run_id: baseline || undefined, review }),
    onSuccess: (j) => setJobId(j.id),
  });

  useEffect(() => {
    if (job.info) {
      qc.invalidateQueries();
      const id = job.info.result?.loop_id as string | undefined;
      if (id) setParams({ loop: id });
    }
  }, [job.info]);

  const active = policies.data?.active;
  const reusable = runs.data?.filter((r) => r.policy_version === active) ?? [];

  return (
    <div>
      <PageHeader
        title="Improvement loop"
        subtitle="Turns failed evaluation runs into a tested policy change. A change is kept only if it fixes what failed and breaks nothing else."
      />

      <div className="mb-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card bodyClassName="p-5">
          <ol className="flex flex-wrap items-center gap-2 text-xs">
            {PIPELINE.map((s, i) => (
              <li key={s} className="flex items-center gap-2">
                <span className="flex items-center gap-2 rounded-full bg-slate-50 py-1 pl-1 pr-3 ring-1 ring-slate-200">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-600 text-[10px] font-semibold text-white">{i + 1}</span>
                  <span className="font-medium text-slate-700">{s}</span>
                </span>
                {i < PIPELINE.length - 1 && <span className="text-slate-300">→</span>}
              </li>
            ))}
          </ol>
          <p className="mt-4 text-sm text-slate-500">
            The analyzer only sees <b>train</b> failures. <b>Holdout</b> scenarios stay hidden and only vote in the gate, so a
            fix has to generalise, not memorise.
          </p>
        </Card>

        <Card title="Run the loop" bodyClassName="p-5 space-y-4">
          <button type="button" onClick={() => setReview((r) => !r)} className="flex w-full items-start gap-3 text-left text-sm">
            <span className={`mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition ${review ? "bg-brand-600" : "bg-slate-300"}`}>
              <span className={`h-4 w-4 rounded-full bg-white shadow transition ${review ? "translate-x-4" : ""}`} />
            </span>
            <span>
              <span className="font-semibold text-slate-800">Require my approval</span>
              <span className="block text-xs text-slate-500">A passing change waits on the Policies page instead of going live.</span>
            </span>
          </button>
          <details className="group text-sm">
            <summary className="flex cursor-pointer list-none items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-800">
              <IconChevron className="h-3.5 w-3.5 transition group-open:rotate-90" /> Advanced options
            </summary>
            <div className="mt-3 space-y-2">
              <Select value={trials} onChange={setTrials} options={TRIAL_OPTIONS} />
              <Select value={attempts} onChange={setAttempts}
                      options={[1, 2, 3].map((n) => ({ value: n, label: `Up to ${n} attempt${n > 1 ? "s" : ""}` }))} />
              <Select value={baseline} onChange={setBaseline}
                      options={[
                        { value: "", label: `Fresh baseline on ${active ?? "live policy"}` },
                        ...reusable.map((r) => ({
                          value: r.run_id,
                          label: `Reuse run · ${r.summary.overall.passed}/${r.summary.overall.total}`,
                          hint: `${shortDate(r.created_at)} · ${r.trials_per_scenario} trial(s)`,
                        })),
                      ]} />
            </div>
          </details>
          <button className="btn-primary w-full" onClick={() => start.mutate()} disabled={start.isPending || job.running}>
            {job.running ? <Spinner /> : <IconPlay className="h-4 w-4" />}
            {job.running ? "Loop running…" : "Start improvement loop"}
          </button>
          <ErrorNote error={start.error} />
        </Card>
      </div>

      {jobId && <Card title="Live progress" className="mb-6"><JobTimeline events={job.events} /></Card>}

      <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
        <div className="space-y-2">
          <div className="label px-1">History</div>
          {loops.data?.length ? loops.data.map((l) => (
            <button key={l.loop_id} onClick={() => setParams({ loop: l.loop_id })}
                    className={`card w-full px-4 py-3 text-left transition hover:ring-brand-300 ${l.loop_id === loopId ? "ring-2 ring-brand-500" : ""}`}>
              <div className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
                {l.start_version} <span className="text-slate-300">→</span> {l.final_version}
                <span className="ml-auto tabular-nums">
                  {l.summary_before.overall.passed}→{l.summary_after.overall.passed}
                  <span className="text-xs font-normal text-slate-400">/{l.summary_after.overall.total}</span>
                </span>
              </div>
              <div className="mt-1 text-xs text-slate-400">{shortDate(l.created_at)}</div>
            </button>
          )) : <Empty>No loops yet.</Empty>}
        </div>
        <div>{loopId ? <LoopDetail loopId={loopId} /> : <Empty>Run the loop to see a before/after.</Empty>}</div>
      </div>
    </div>
  );
}

function LoopDetail({ loopId }: { loopId: string }) {
  const loop = useQuery({ queryKey: ["loop", loopId], queryFn: () => api.loop(loopId) });
  const policies = useQuery({ queryKey: ["policies"], queryFn: api.policies });
  if (loop.isLoading) return <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Loading…</div>;
  if (!loop.data) return <ErrorNote error={loop.error} />;
  const l: LoopReport = loop.data;
  const b = l.summary_before, a = l.summary_after;
  const stillPending = !!l.awaiting_review &&
    policies.data?.versions.find((v) => v.version === l.awaiting_review)?.status === "awaiting_review";
  const attempts = l.iterations.flatMap((it) => it.attempts.filter((x) => x.attempt > 0));

  return (
    <div className="space-y-5">
      <div className="card overflow-hidden">
        <div className="bg-gradient-to-br from-slate-900 to-slate-800 px-6 py-5 text-white">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-slate-400">
            <IconSpark className="h-4 w-4" /> Outcome
          </div>
          <div className="mt-1 text-base font-semibold">{l.outcome.split(". Approve")[0]}</div>
          <div className="mt-5 grid grid-cols-3 gap-4">
            {([["Overall", b.overall, a.overall], ["Train", b.train, a.train], ["Holdout (unseen)", b.holdout, a.holdout]] as const)
              .map(([label, x, y]) => (
                <div key={label}>
                  <div className="text-xs text-slate-400">{label}</div>
                  <div className="mt-0.5 text-2xl font-semibold tabular-nums">
                    {x.passed} <span className="text-slate-500">→</span>{" "}
                    <span className={y.passed > x.passed ? "text-emerald-300" : y.passed < x.passed ? "text-rose-300" : ""}>{y.passed}</span>
                    <span className="text-sm text-slate-500">/{y.total}</span>
                  </div>
                </div>
              ))}
          </div>
        </div>
        {stillPending && (
          <div className="flex flex-wrap items-center justify-between gap-3 bg-amber-50 px-6 py-3 text-sm text-amber-900">
            <span className="flex items-center gap-2"><IconAlert className="h-4 w-4" />
              <b>{l.awaiting_review}</b> passed every gate rule and is waiting for your approval.</span>
            <Link className="btn-primary" to="/policies">Review &amp; approve</Link>
          </div>
        )}
      </div>

      {attempts.map((att) => (
        <Card key={att.attempt}
              title={<span className="flex items-center gap-2">Attempt {att.attempt}
                {att.candidate_version && <Badge tone="violet">{att.candidate_version}</Badge>}
                {att.gate && <PassBadge passed={att.accepted} />}</span>}
              right={att.candidate_run_id && (
                <Link className="text-xs font-medium text-brand-700 hover:underline" to={`/evals?run=${att.candidate_run_id}`}>View run</Link>)}>
          <div className="space-y-4">
            {att.note && <div className="text-sm text-amber-800">{att.note}</div>}
            {att.proposals.map((p, i) => (
              <div key={i} className="rounded-xl bg-violet-50/60 p-3 ring-1 ring-violet-100">
                <div className="label mb-1 text-violet-500">What went wrong · {p.failure_cluster}</div>
                <div className="text-sm text-slate-800">{p.root_cause}</div>
                <div className="mt-1 text-xs text-slate-500">Expected effect: {p.expected_effect}</div>
              </div>
            ))}
            {att.code_tickets.map((p, i) => (
              <div key={i} className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200">
                <b>Needs a code change:</b> {p.code_change_ticket}
              </div>
            ))}
            {att.diff && <div><div className="label mb-1.5">Policy change</div><PolicyDiff diff={att.diff} /></div>}
            {att.gate && (
              <div>
                <div className="label mb-1.5">Regression gate</div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(att.gate.rules).map(([k, v]) => (
                    <Badge key={k} tone={v ? "green" : "red"}>{v ? "✓" : "✗"} {k.replaceAll("_", " ")}</Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>
      ))}

      {l.before_after.length > 0 && (
        <Card title={`Scenario by scenario · ${l.start_version} → ${l.awaiting_review ?? l.final_version}`} bodyClassName="p-0">
          <CompareTable rows={l.before_after} before={l.start_version} after={l.awaiting_review ?? l.final_version} />
        </Card>
      )}
    </div>
  );
}
