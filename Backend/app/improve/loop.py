"""The improvement loop:

  baseline run (active policy) -> train failures -> analyzer proposals -> filtered edits ->
  candidate policy vN+1 -> full re-run -> regression gate -> activate or reject (+ feedback, retry)

Holdout scenarios are never shown to the analyzer; they only vote in the gate.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Callable

from pydantic import BaseModel

from app.config import REPORTS_DIR
from app.evals.report import load_run, persist_run
from app.evals.runner import RunResult, aggregate, run_suite, summarize
from app.evals.scenarios import Scenario, load_scenarios
from app.improve.analyzer import analyze
from app.improve.applier import apply_edits, bump_title
from app.improve.gate import GateDecision, compare, evaluate
from app.llm.base import LLMBudgetExceeded, LLMError

LOOPS_DIR = REPORTS_DIR / "loops"


class AttemptReport(BaseModel):
    attempt: int
    analyzer_model: str = ""
    proposals: list[dict] = []
    code_tickets: list[dict] = []
    applied_edits: list[str] = []
    rejected_edits: list[str] = []
    candidate_version: str | None = None
    candidate_run_id: str | None = None
    diff: str = ""
    gate: dict | None = None
    rechecked: list[str] = []
    accepted: bool = False
    note: str = ""


class IterationReport(BaseModel):
    iteration: int
    baseline_version: str
    baseline_run_id: str
    failing_train: list[str]
    attempts: list[AttemptReport] = []
    accepted_version: str | None = None


class LoopReport(BaseModel):
    loop_id: str
    created_at: str
    trials: int
    scenario_ids: list[str]
    start_version: str
    final_version: str
    first_run_id: str = ""
    final_run_id: str = ""
    iterations: list[IterationReport] = []
    review_mode: bool = False
    awaiting_review: str | None = None  # candidate that passed the gate but needs human approval
    before_after: list[dict] = []
    summary_before: dict = {}
    summary_after: dict = {}
    outcome: str = ""


async def _analyze_with_fallback(rt, policy_text, baseline, sc_by_id, failing, feedback, att, emit):
    """Pro first; if the key can't use it (no access, quota), fall back to Flash and record it."""
    primary, fallback = rt.settings.model_analyzer, rt.settings.model_analyzer_fallback
    try:
        result = await analyze(rt.llm, primary, policy_text, baseline, sc_by_id, failing, feedback)
        att.analyzer_model = primary
        return result
    except LLMBudgetExceeded:
        raise
    except LLMError as exc:
        if not fallback or fallback == primary:
            raise
        emit({"type": "analyzer_fallback", "from": primary, "to": fallback, "reason": str(exc)[:200]})
        result = await analyze(rt.llm, fallback, policy_text, baseline, sc_by_id, failing, feedback)
        att.analyzer_model = fallback
        att.note = f"Analyzer fell back from {primary} to {fallback}: {str(exc)[:120]}"
        return result


async def _recheck(rt, run: RunResult, scenarios: dict[str, Scenario], ids: list[str], trials: int,
                   emit) -> RunResult:
    """Regressions can be noise. Re-run the regressed scenarios on the candidate and pool the trials."""
    extra = await run_suite(rt, run.policy_version, [scenarios[i] for i in ids], trials, emit,
                            label=f"recheck {run.policy_version}")
    extra_by = extra.by_id()
    results = []
    for r in run.results:
        if r.scenario_id in extra_by:
            more = [t.model_copy(update={"trial": t.trial + run.trials_per_scenario})
                    for t in extra_by[r.scenario_id].trials]
            r = aggregate(scenarios[r.scenario_id], r.trials + more)
        results.append(r)
    merged = run.model_copy(update={"results": results, "summary": summarize(results)})
    await persist_run(rt.repo, merged)
    return merged


async def run_loop(rt, trials: int, scenario_ids: list[str] | None = None, max_attempts: int = 3,
                   iterations: int = 1, baseline_run_id: str | None = None,
                   progress: Callable[[dict], None] | None = None, review: bool = False) -> LoopReport:
    """review=True: a candidate that passes the gate is NOT activated; it waits for a human
    to approve it (policy approve vN) or reject it (policy reject vN)."""
    emit = progress or (lambda e: None)
    scenarios = load_scenarios(ids=scenario_ids)
    sc_by_id = {s.id: s for s in scenarios}
    policies = rt.policies
    version = policies.active_version()
    loop_id = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
    report = LoopReport(loop_id=loop_id, created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        trials=trials, scenario_ids=[s.id for s in scenarios], start_version=version,
                        final_version=version, review_mode=review)
    emit({"type": "loop_started", "loop_id": loop_id, "policy_version": version})

    if baseline_run_id:
        baseline = load_run(baseline_run_id)
        if baseline.policy_version != version:
            raise ValueError(f"Baseline run is for {baseline.policy_version}, active policy is {version}")
        emit({"type": "baseline_reused", "run_id": baseline.run_id})
    else:
        baseline = await run_suite(rt, version, scenarios, trials, emit, label="baseline")
        await persist_run(rt.repo, baseline)
    first = baseline
    report.first_run_id = baseline.run_id

    for it in range(1, iterations + 1):
        failing = [r.scenario_id for r in baseline.results
                   if r.split == "train" and r.status == "ok" and not r.passed]
        itr = IterationReport(iteration=it, baseline_version=version, baseline_run_id=baseline.run_id,
                              failing_train=failing)
        report.iterations.append(itr)
        emit({"type": "iteration_started", "iteration": it, "failing_train": failing})
        if not failing:
            itr.attempts.append(AttemptReport(attempt=0, note="No failing train scenarios: nothing to fix."))
            break

        policy_text = policies.text(version)
        feedback: list[str] | None = None
        for attempt in range(1, max_attempts + 1):
            att = AttemptReport(attempt=attempt)
            itr.attempts.append(att)
            emit({"type": "analyzing", "iteration": it, "attempt": attempt})
            try:
                analysis = await _analyze_with_fallback(rt, policy_text, baseline, sc_by_id, failing, feedback,
                                                        att, emit)
            except LLMError as exc:
                att.note = f"Analyzer failed: {exc}"
                emit({"type": "attempt_failed", "reason": att.note})
                break
            att.proposals = [p.model_dump() for p in analysis.proposals if p.fix_type == "policy_edit"]
            att.code_tickets = [p.model_dump() for p in analysis.proposals if p.fix_type == "needs_code_change"]
            edits = [e for p in analysis.proposals if p.fix_type == "policy_edit" for e in p.edits]
            emit({"type": "proposals", "attempt": attempt, "proposals": att.proposals,
                  "code_tickets": att.code_tickets})

            new_text, att.applied_edits, att.rejected_edits = apply_edits(policy_text, edits, set(sc_by_id))
            if not att.applied_edits:
                att.note = "No applicable policy edits."
                feedback = att.rejected_edits or ["You proposed no policy edits. Propose at least one general rule."]
                emit({"type": "attempt_failed", "reason": att.note, "rejected": att.rejected_edits})
                continue

            targets = sorted({t for p in analysis.proposals if p.fix_type == "policy_edit"
                              for t in p.target_scenarios} & set(failing)) or failing
            clusters = ", ".join(p["failure_cluster"] for p in att.proposals)
            cand = policies.create_candidate(version, bump_title(new_text, policies.next_version()),
                                             patch=att.proposals,
                                             notes=f"loop {loop_id} it{it} attempt{attempt}: {clusters}")
            att.candidate_version = cand.version
            att.diff = policies.diff(version, cand.version)
            emit({"type": "candidate_created", "version": cand.version, "diff": att.diff,
                  "applied": att.applied_edits, "rejected": att.rejected_edits})

            cand_run = await run_suite(rt, cand.version, scenarios, trials, emit, label=f"candidate {cand.version}")
            await persist_run(rt.repo, cand_run)
            decision: GateDecision = evaluate(baseline, cand_run, targets)
            if not decision.accepted and decision.regressed and \
                    all(v for k, v in decision.rules.items() if k != "no_regressions"):
                emit({"type": "rechecking", "scenarios": decision.regressed})
                att.rechecked = decision.regressed
                cand_run = await _recheck(rt, cand_run, sc_by_id, decision.regressed, trials, emit)
                decision = evaluate(baseline, cand_run, targets)
            att.candidate_run_id = cand_run.run_id
            att.gate = decision.model_dump()
            att.accepted = decision.accepted
            emit({"type": "gate", "version": cand.version, "accepted": decision.accepted,
                  "rules": decision.rules, "reasons": decision.reasons, "table": decision.table})

            if decision.accepted:
                itr.accepted_version = cand.version
                if review:
                    # Gate passed, but a human decides: nothing changes for live patients yet.
                    policies.set_status(cand.version, "awaiting_review")
                    report.awaiting_review = cand.version
                    emit({"type": "awaiting_review", "version": cand.version, "active": version})
                    baseline = cand_run
                else:
                    policies.activate(cand.version)
                    version, baseline = cand.version, cand_run
                break
            policies.set_status(cand.version, "rejected")
            feedback = decision.reasons + [f"Rejected edits were: {att.applied_edits}"]

        if not itr.accepted_version or report.awaiting_review:
            break  # in review mode, never build v3 on top of an unapproved v2

    report.final_version = version
    report.final_run_id = baseline.run_id
    report.summary_before, report.summary_after = first.summary, baseline.summary
    report.before_after = compare(first, baseline) if baseline.run_id != first.run_id else []
    accepted = [i.accepted_version for i in report.iterations if i.accepted_version]
    if report.awaiting_review:
        report.outcome = (f"{report.awaiting_review} passed the gate and is AWAITING REVIEW; {version} is still "
                          f"live. Approve with: python -m app.cli policy approve {report.awaiting_review}")
    elif accepted:
        report.outcome = f"Accepted {', '.join(accepted)}: {first.policy_version} -> {version}"
    else:
        report.outcome = f"No change accepted; {version} remains active"
    save_loop(report)
    await mirror_to_db(rt, report)
    emit({"type": "loop_finished", "loop_id": loop_id, "outcome": report.outcome,
          "final_version": version, "awaiting_review": report.awaiting_review,
          "before_after": report.before_after})
    return report


# ------------------------------------------------------------------ persistence

def render_loop_markdown(r: LoopReport) -> str:
    out = [f"# Improvement loop `{r.loop_id}`", "",
           f"- **Outcome: {r.outcome}**",
           f"- Trials per scenario: {r.trials}; scenarios: {len(r.scenario_ids)}",
           f"- Baseline run: `{r.first_run_id}`; final run: `{r.final_run_id}`", ""]
    sb, sa = r.summary_before, r.summary_after
    if sb and sa:
        out += ["| | Before | After |", "|---|---|---|"]
        for k in ("overall", "train", "holdout"):
            out.append(f"| {k} | {sb[k]['passed']}/{sb[k]['total']} (score {sb[k]['mean_score']}) | "
                       f"{sa[k]['passed']}/{sa[k]['total']} (score {sa[k]['mean_score']}) |")
        out.append("")
    if r.before_after:
        out += ["## Before / after by scenario", "",
                "| Scenario | Split | Before | After | Change |", "|---|---|---|---|---|"]
        out += [f"| {x['scenario_id']} | {x['split']} | {x['before_pass_rate']} | {x['after_pass_rate']} | {x['change']} |"
                for x in r.before_after]
        out.append("")
    for itr in r.iterations:
        out += [f"## Iteration {itr.iteration} (from {itr.baseline_version})", "",
                f"Failing train scenarios: {itr.failing_train or 'none'}", ""]
        for att in itr.attempts:
            if att.attempt == 0:
                out += [att.note, ""]
                continue
            verdict = ("PASSED GATE, awaiting review" if att.candidate_version == r.awaiting_review
                       else "ACCEPTED" if att.accepted else "rejected")
            out += [f"### Attempt {att.attempt}: {att.candidate_version or '-'} {verdict}"
                    + (f" (analyzer: {att.analyzer_model})" if att.analyzer_model else ""), ""]
            if att.note:
                out += [att.note, ""]
            for p in att.proposals:
                out += [f"- **{p['failure_cluster']}**: {p['root_cause']}",
                        f"  - expected effect: {p['expected_effect']} (targets: {p['target_scenarios']})"]
            for t in att.code_tickets:
                out += [f"- **Code ticket ({t['failure_cluster']})**: {t.get('code_change_ticket')}"]
            if att.rejected_edits:
                out += ["", "Edits refused by the applier:"] + [f"- {x}" for x in att.rejected_edits]
            if att.diff:
                out += ["", "```diff", att.diff.rstrip(), "```"]
            if att.gate:
                out += ["", "Gate: " + ", ".join(f"{k}={'yes' if v else 'NO'}" for k, v in att.gate["rules"].items())]
                out += [f"- {x}" for x in att.gate["reasons"]]
                if att.rechecked:
                    out.append(f"- Regressions re-checked with extra trials: {att.rechecked}")
            out.append("")
    return "\n".join(out) + "\n"


async def mirror_to_db(rt, report: LoopReport | None = None) -> None:
    """Copy policy versions (with text) and the loop report into MongoDB for reviewers."""
    try:
        for v in rt.policies.versions():
            await rt.repo.upsert("policies", "version", {**v.model_dump(), "content": rt.policies.text(v.version),
                                                         "active": v.version == rt.policies.active_version()})
        if report:
            await rt.repo.upsert("loop_reports", "loop_id", report.model_dump(mode="json"))
    except Exception:
        pass  # read-only user or memory store hiccup: files remain the source of truth


def save_loop(r: LoopReport) -> None:
    LOOPS_DIR.mkdir(parents=True, exist_ok=True)
    (LOOPS_DIR / f"{r.loop_id}.json").write_text(r.model_dump_json(indent=2), encoding="utf-8")
    (LOOPS_DIR / f"{r.loop_id}.md").write_text(render_loop_markdown(r), encoding="utf-8")


def list_loops() -> list[dict]:
    if not LOOPS_DIR.exists():
        return []
    out = []
    for p in sorted(LOOPS_DIR.glob("*.json"), reverse=True):
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({k: d[k] for k in ("loop_id", "created_at", "start_version", "final_version", "outcome",
                                      "summary_before", "summary_after")})
    return out


def load_loop(loop_id: str) -> LoopReport:
    return LoopReport.model_validate_json((LOOPS_DIR / f"{loop_id}.json").read_text(encoding="utf-8"))
