import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { IconCheck, IconChevron, IconPlay, IconX } from "../components/icons";
import { JobTimeline } from "../components/JobTimeline";
import { ToolTrace } from "../components/ToolTrace";
import { TranscriptViewer } from "../components/TranscriptViewer";
import {
  Badge, Card, Empty, ErrorNote, PageHeader, PassBadge, ScoreBar, Select, Spinner, Stat, Tabs, TrialDots, humanize,
  shortDate,
} from "../components/ui";
import { useJob } from "../hooks/useJob";
import type { ScenarioResult, TrialResult } from "../types";

export const TRIAL_OPTIONS = [
  { value: 1, label: "1 trial per scenario", hint: "Quick smoke test" },
  { value: 2, label: "2 trials per scenario" },
  { value: 3, label: "3 trials per scenario", hint: "Recommended: majority vote" },
];

export default function EvalsPage() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const runId = params.get("run") ?? runs.data?.[0]?.run_id ?? null;

  const [trials, setTrials] = useState(3);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const start = useMutation({ mutationFn: () => api.startEval({ trials }), onSuccess: (j) => setJobId(j.id) });

  useEffect(() => {
    if (job.info?.status === "done") {
      qc.invalidateQueries({ queryKey: ["runs"] });
      const id = job.info.result?.run_id as string | undefined;
      if (id) setParams({ run: id });
    }
  }, [job.info]);

  return (
    <div>
      <PageHeader
        title="Evaluations"
        subtitle="A simulated patient talks to the real agent in a fresh test clinic. Each conversation is scored on what actually happened in the database, plus a transcript review."
        actions={
          <>
            <Select className="w-52" value={trials} onChange={setTrials} options={TRIAL_OPTIONS} />
            <button className="btn-primary" onClick={() => start.mutate()} disabled={start.isPending || job.running}>
              {job.running ? <Spinner /> : <IconPlay className="h-4 w-4" />}
              {job.running ? "Running…" : "Run evaluation"}
            </button>
          </>
        }
      />
      <ErrorNote error={start.error} />
      {jobId && (
        <Card title="Live run" className="mb-6"><JobTimeline events={job.events} /></Card>
      )}

      <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
        <div className="space-y-2">
          <div className="label px-1">History</div>
          {runs.data?.length ? runs.data.map((r) => (
            <button key={r.run_id} onClick={() => setParams({ run: r.run_id })}
                    className={`card w-full px-4 py-3 text-left transition hover:ring-brand-300 ${r.run_id === runId ? "ring-2 ring-brand-500" : ""}`}>
              <div className="flex items-center justify-between">
                <Badge tone="brand">policy {r.policy_version}</Badge>
                <span className="text-lg font-semibold tabular-nums text-slate-900">
                  {r.summary.overall.passed}<span className="text-sm text-slate-400">/{r.summary.overall.total}</span>
                </span>
              </div>
              <div className="mt-1.5 text-xs text-slate-500">{shortDate(r.created_at)} · {r.trials_per_scenario} trial{r.trials_per_scenario > 1 ? "s" : ""}</div>
            </button>
          )) : <Empty>No runs yet.</Empty>}
        </div>
        <div>{runId ? <RunDetail runId={runId} /> : <Empty>Run an evaluation to see results.</Empty>}</div>
      </div>
    </div>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId) });
  const [open, setOpen] = useState<string | null>(null);
  if (run.isLoading) return <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Loading…</div>;
  if (!run.data) return <ErrorNote error={run.error} />;
  const s = run.data.summary;
  const groups: { title: string; hint: string; rows: ScenarioResult[] }[] = [
    { title: "Train", hint: "the improvement loop learns from these", rows: run.data.results.filter((r) => r.split === "train") },
    { title: "Holdout", hint: "never shown to the loop; checks fixes generalise", rows: run.data.results.filter((r) => r.split === "holdout") },
  ];
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat accent label="Scenarios passed" value={`${s.overall.passed}/${s.overall.total}`} sub={`policy ${run.data.policy_version}`} />
        <Stat label="Train" value={`${s.train.passed}/${s.train.total}`} />
        <Stat label="Holdout" value={`${s.holdout.passed}/${s.holdout.total}`} />
        <Stat label="Mean score" value={s.overall.mean_score.toFixed(2)} sub={s.error_trials ? `${s.error_trials} errored trials` : undefined} />
      </div>
      {groups.map((g) => (
        <Card key={g.title} bodyClassName=""
              title={<span>{g.title} <span className="ml-1 font-normal text-slate-400">· {g.hint}</span></span>}>
          <ul className="divide-y divide-slate-100">
            {g.rows.map((r) => (
              <ScenarioRow key={r.scenario_id} r={r} open={open === r.scenario_id}
                           toggle={() => setOpen(open === r.scenario_id ? null : r.scenario_id)} />
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}

function ScenarioRow({ r, open, toggle }: { r: ScenarioResult; open: boolean; toggle: () => void }) {
  return (
    <li>
      <button onClick={toggle} className="flex w-full items-center gap-4 px-5 py-3 text-left hover:bg-slate-50/80">
        <IconChevron className={`h-4 w-4 shrink-0 text-slate-400 transition ${open ? "rotate-90" : ""}`} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-slate-800">{humanize(r.scenario_id)}</div>
          <div className="text-xs text-slate-400">{r.category}</div>
        </div>
        <TrialDots trials={r.trials} />
        <span className="hidden sm:block"><ScoreBar value={r.mean_score} /></span>
        <PassBadge passed={r.passed} error={r.status === "error"} />
      </button>
      {open && (
        <div className="bg-slate-50/60 px-5 pb-5 pt-1">
          <p className="mb-3 text-sm text-slate-500">{r.description}</p>
          <TrialPanel trials={r.trials} />
        </div>
      )}
    </li>
  );
}

function TrialPanel({ trials }: { trials: TrialResult[] }) {
  const firstFail = trials.find((t) => !t.passed) ?? trials[0];
  const [idx, setIdx] = useState(trials.indexOf(firstFail));
  const [tab, setTab] = useState<"result" | "conversation" | "activity">("result");
  const t = trials[idx];
  return (
    <div className="card p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1.5">
          {trials.map((x, i) => (
            <button key={i} onClick={() => setIdx(i)}
                    className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium ring-1 ${
                      i === idx ? "bg-slate-900 text-white ring-slate-900" : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${x.status === "error" ? "bg-amber-400" : x.passed ? "bg-emerald-400" : "bg-rose-400"}`} />
              Trial {x.trial}
            </button>
          ))}
        </div>
        <Tabs value={tab} onChange={setTab}
              tabs={[{ id: "result", label: "Result" }, { id: "conversation", label: "Conversation" }, { id: "activity", label: "Activity" }]} />
      </div>

      {t.error && <ErrorNote error={t.error} />}
      {tab === "result" && (
        <div className="grid gap-5 md:grid-cols-2">
          <div>
            <div className="label mb-2">Checks · database &amp; tool trace</div>
            <ul className="space-y-2">
              {t.checks.map((c, i) => (
                <li key={i} className="flex gap-2.5 text-sm">
                  <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${c.passed ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>
                    {c.passed ? <IconCheck className="h-3 w-3" /> : <IconX className="h-3 w-3" />}
                  </span>
                  <div>
                    <span className="font-medium text-slate-700">{humanize(c.type)}</span>
                    {c.critical && <span className="ml-1.5 text-[10px] font-semibold uppercase text-rose-500">critical</span>}
                    {!c.passed && <div className="text-xs text-slate-500">{c.detail}</div>}
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="label mb-2">Judge · transcript only</div>
            <ul className="space-y-2">
              {t.judge.scores?.map((s) => (
                <li key={s.id} className="text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-700">{humanize(s.id)}</span>
                    <span className={`text-xs font-semibold tabular-nums ${s.passed ? "text-emerald-600" : "text-rose-600"}`}>{s.score}/5</span>
                  </div>
                  <div className="text-xs text-slate-500">{s.reason}</div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {tab === "conversation" && <TranscriptViewer lines={t.transcript} />}
      {tab === "activity" && <ToolTrace events={t.tool_trace} />}
    </div>
  );
}
