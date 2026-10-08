"""Eval harness: for each scenario x trial, seed a fresh sandbox on a frozen clock, let the
simulated patient talk to the real agent, then score the result with checks + judge."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Callable

from pydantic import BaseModel

from app.agent.orchestrator import ClinicAgent
from app.clinic.dates import Clock
from app.db.seed import seed_sandbox
from app.evals.checks import TrialArtifacts, run_checks
from app.evals.judge import judge_transcript
from app.evals.scenarios import Scenario
from app.evals.simulator import PatientSimulator
from app.llm.base import LLMError

PASS_SCORE = 0.75
CHECK_WEIGHT, JUDGE_WEIGHT = 0.7, 0.3

ProgressFn = Callable[[dict], None]


class TrialResult(BaseModel):
    scenario_id: str
    trial: int
    status: str  # "ok" | "error"
    passed: bool = False
    score: float = 0.0
    critical_failures: list[str] = []
    checks: list[dict] = []
    judge: dict = {}
    transcript: list[dict] = []
    tool_trace: list[dict] = []
    flags: list[str] = []
    ended_by: str = ""
    error: str | None = None
    session_id: str = ""


class ScenarioResult(BaseModel):
    scenario_id: str
    split: str
    category: str
    description: str
    trials: list[TrialResult]
    pass_rate: float
    passed: bool
    mean_score: float
    status: str  # "ok" | "error"


class RunResult(BaseModel):
    run_id: str
    policy_version: str
    created_at: str
    trials_per_scenario: int
    models: dict
    results: list[ScenarioResult]
    summary: dict
    llm_usage: dict = {}

    def by_id(self) -> dict[str, ScenarioResult]:
        return {r.scenario_id: r for r in self.results}


def score_trial(checks: list[dict], judge: dict) -> tuple[bool, float, list[str]]:
    critical = [c["type"] for c in checks if c["critical"] and not c["passed"]]
    critical += [f"rubric:{s['id']}" for s in judge.get("scores", []) if s["critical"] and not s["passed"]]
    check_frac = sum(c["passed"] for c in checks) / len(checks) if checks else 1.0
    score = round(CHECK_WEIGHT * check_frac + JUDGE_WEIGHT * judge.get("normalized", 1.0), 3)
    if critical:
        return False, 0.0, critical
    return score >= PASS_SCORE, score, []


async def run_trial(rt, scenario: Scenario, policy_version: str, run_id: str, trial: int) -> TrialResult:
    repo, settings = rt.repo, rt.settings
    sandbox = f"eval-{run_id}-{scenario.id}-{trial}"
    clock = Clock.from_iso(settings.clinic_timezone, scenario.now)
    await seed_sandbox(repo, sandbox, clock, scenario.seed)
    before = {a.id: a for a in await repo.all_appointments(sandbox)}
    agent = ClinicAgent(repo, rt.llm, clock, settings, rt.policies)
    session = await agent.start_session(sandbox, policy_version, faults=scenario.faults)
    sim = PatientSimulator(rt.llm, settings, scenario)

    transcript = [{"role": "agent", "text": agent.greeting(), "turn": 0}]
    flags: list[str] = []
    ended_by, error = "max_turns", None
    try:
        msg, done = (scenario.opening, False) if scenario.opening else await sim.next_message(transcript)
        for turn in range(1, scenario.max_turns + 1):
            res = await agent.respond(session.id, msg)
            flags += res.flags
            if "llm_error" in res.flags:
                raise LLMError("agent model call failed")
            transcript += [{"role": "patient", "text": msg, "turn": turn},
                           {"role": "agent", "text": res.reply, "turn": turn}]
            msg, done = await sim.next_message(transcript)
            if done:
                # The patient's last words still reach the agent: "Yes, please confirm [END]" must be
                # answered, otherwise a perfectly good conversation looks like it never booked.
                if msg:
                    res = await agent.respond(session.id, msg)
                    flags += res.flags
                    transcript += [{"role": "patient", "text": msg, "turn": turn + 1},
                                   {"role": "agent", "text": res.reply, "turn": turn + 1}]
                ended_by = "patient"
                break
    except Exception as exc:  # infra problems (rate limits, budget) are errors, not agent failures
        ended_by, error = "error", f"{type(exc).__name__}: {exc}"

    try:
        audit = await repo.audit_for_session(session.id)
        trace = [{k: e.get(k) for k in ("seq", "turn", "tool", "args", "result", "denied_by", "stage_after")}
                 for e in audit]
        if error:
            return TrialResult(scenario_id=scenario.id, trial=trial, status="error", error=error,
                               transcript=transcript, tool_trace=trace, flags=flags, ended_by=ended_by,
                               session_id=session.id)
        final = await agent.load_session(session.id)
        artifacts = TrialArtifacts(
            scenario=scenario, session_id=session.id, sandbox_id=sandbox, clock=clock, repo=repo,
            transcript=transcript, audit=trace, appointments_before=before,
            appointments_after=await repo.all_appointments(sandbox),
            escalations=await repo.escalations(sandbox, session.id),
            final_state=final.state.model_dump(mode="json"), ended_by=ended_by, flags=flags,
        )
        checks = [c.to_dict() for c in await run_checks(artifacts, scenario.checks)]
        judge = (await judge_transcript(rt.llm, settings, scenario, transcript)).model_dump()
        if judge.get("error"):
            return TrialResult(scenario_id=scenario.id, trial=trial, status="error",
                               error=f"judge: {judge['error']}", checks=checks, transcript=transcript,
                               tool_trace=trace, flags=flags, ended_by=ended_by, session_id=session.id)
        passed, score, critical = score_trial(checks, judge)
        return TrialResult(scenario_id=scenario.id, trial=trial, status="ok", passed=passed, score=score,
                           critical_failures=critical, checks=checks, judge=judge, transcript=transcript,
                           tool_trace=trace, flags=flags, ended_by=ended_by, session_id=session.id)
    finally:
        await repo.reset_sandbox(sandbox)  # clinic data only; session + audit log are kept for inspection


def aggregate(scenario: Scenario, trials: list[TrialResult]) -> ScenarioResult:
    valid = [t for t in trials if t.status == "ok"]
    n_pass = sum(t.passed for t in valid)
    return ScenarioResult(
        scenario_id=scenario.id, split=scenario.split, category=scenario.category,
        description=scenario.description, trials=sorted(trials, key=lambda t: t.trial),
        pass_rate=round(n_pass / len(valid), 3) if valid else 0.0,
        passed=bool(valid) and n_pass * 2 > len(valid),  # strict majority of valid trials
        mean_score=round(sum(t.score for t in valid) / len(valid), 3) if valid else 0.0,
        status="ok" if valid else "error",
    )


def summarize(results: list[ScenarioResult]) -> dict:
    def block(rs: list[ScenarioResult]) -> dict:
        return {"passed": sum(r.passed for r in rs), "total": len(rs),
                "mean_score": round(sum(r.mean_score for r in rs) / len(rs), 3) if rs else 0.0}

    cats = sorted({r.category for r in results})
    return {
        "overall": block(results),
        "train": block([r for r in results if r.split == "train"]),
        "holdout": block([r for r in results if r.split == "holdout"]),
        "by_category": {c: block([r for r in results if r.category == c]) for c in cats},
        "errors": sum(r.status == "error" for r in results),
        "error_trials": sum(t.status == "error" for r in results for t in r.trials),
    }


def new_run_id(policy_version: str) -> str:
    return f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{policy_version}-{uuid.uuid4().hex[:4]}"


async def run_suite(rt, policy_version: str, scenarios: list[Scenario], trials: int,
                    progress: ProgressFn | None = None, label: str = "") -> RunResult:
    run_id = new_run_id(policy_version)
    sem = asyncio.Semaphore(rt.settings.eval_concurrency)
    total, done = len(scenarios) * trials, 0
    emit = progress or (lambda e: None)
    emit({"type": "run_started", "run_id": run_id, "policy_version": policy_version, "label": label,
          "scenarios": len(scenarios), "trials": trials})

    async def one(sc: Scenario, k: int) -> TrialResult:
        nonlocal done
        async with sem:
            try:
                res = await run_trial(rt, sc, policy_version, run_id, k)
            except Exception as exc:  # never let one trial kill the whole run
                res = TrialResult(scenario_id=sc.id, trial=k, status="error", error=f"{type(exc).__name__}: {exc}")
        done += 1
        emit({"type": "trial_done", "run_id": run_id, "scenario_id": sc.id, "trial": k, "status": res.status,
              "passed": res.passed, "score": res.score, "critical_failures": res.critical_failures,
              "progress": f"{done}/{total}", "error": res.error})
        return res

    all_trials = await asyncio.gather(*(one(sc, k) for sc in scenarios for k in range(1, trials + 1)))
    results = [aggregate(sc, [t for t in all_trials if t.scenario_id == sc.id]) for sc in scenarios]
    usage = rt.llm.usage_summary() if hasattr(rt.llm, "usage_summary") else {}
    run = RunResult(
        run_id=run_id, policy_version=policy_version,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), trials_per_scenario=trials,
        models={"agent": rt.settings.model_agent, "simulator": rt.settings.model_simulator,
                "judge": rt.settings.model_judge},
        results=results, summary=summarize(results), llm_usage=usage,
    )
    emit({"type": "run_finished", "run_id": run_id, "policy_version": policy_version, "summary": run.summary})
    return run
