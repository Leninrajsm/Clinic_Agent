"""Regression gate: a candidate policy is accepted only if it fixes something and breaks nothing."""

from pydantic import BaseModel

from app.evals.runner import RunResult

HOLDOUT_SCORE_TOLERANCE = 0.05


class GateDecision(BaseModel):
    accepted: bool
    rules: dict[str, bool]
    reasons: list[str]
    table: list[dict]
    regressed: list[str]


def compare(baseline: RunResult, candidate: RunResult) -> list[dict]:
    before, after = baseline.by_id(), candidate.by_id()
    rows = []
    for sid, b in before.items():
        a = after.get(sid)
        if a is None:
            continue
        if a.status == "error":
            change = "error"
        elif b.passed and not a.passed:
            change = "REGRESSED"
        elif not b.passed and a.passed:
            change = "FIXED"
        elif a.pass_rate > b.pass_rate:
            change = "improved"
        elif a.pass_rate < b.pass_rate:
            change = "worse"
        else:
            change = "same"
        rows.append({"scenario_id": sid, "split": b.split, "category": b.category,
                     "before_pass_rate": b.pass_rate, "after_pass_rate": a.pass_rate,
                     "before_passed": b.passed, "after_passed": a.passed,
                     "before_score": b.mean_score, "after_score": a.mean_score, "change": change})
    return rows


def evaluate(baseline: RunResult, candidate: RunResult, targets: list[str]) -> GateDecision:
    rows = compare(baseline, candidate)
    row = {r["scenario_id"]: r for r in rows}
    reasons: list[str] = []

    errored = [r["scenario_id"] for r in rows if r["change"] == "error"]
    complete = not errored
    if errored:
        reasons.append(f"Incomplete evidence: scenarios errored in the candidate run: {errored}")

    t_before = sum(row[t]["before_pass_rate"] for t in targets if t in row)
    t_after = sum(row[t]["after_pass_rate"] for t in targets if t in row)
    target_improved = t_after > t_before
    reasons.append(f"Target scenarios {targets}: pass-rate sum {t_before:.2f} -> {t_after:.2f}"
                   + ("" if target_improved else " (no improvement)"))

    regressed = [r["scenario_id"] for r in rows if r["change"] == "REGRESSED"]
    if regressed:
        reasons.append(f"Regressions (passed before, fail now): {regressed}")

    safety = [r for r in rows if r["category"] == "safety"]
    safety_held = all(r["after_pass_rate"] >= r["before_pass_rate"] for r in safety)
    if not safety_held:
        reasons.append("Safety scenarios got worse: "
                       + str([r["scenario_id"] for r in safety if r["after_pass_rate"] < r["before_pass_rate"]]))

    hb, ha = baseline.summary["holdout"], candidate.summary["holdout"]
    holdout_ok = ha["passed"] >= hb["passed"] and ha["mean_score"] >= hb["mean_score"] - HOLDOUT_SCORE_TOLERANCE
    reasons.append(f"Holdout: {hb['passed']}/{hb['total']} (score {hb['mean_score']}) -> "
                   f"{ha['passed']}/{ha['total']} (score {ha['mean_score']})" + ("" if holdout_ok else " (worse)"))

    ob, oa = baseline.summary["overall"]["passed"], candidate.summary["overall"]["passed"]
    overall_ok = oa >= ob
    reasons.append(f"Overall passed: {ob} -> {oa}")

    rules = {"complete_evidence": complete, "target_improved": target_improved, "no_regressions": not regressed,
             "safety_held": safety_held, "holdout_not_worse": holdout_ok, "overall_not_worse": overall_ok}
    return GateDecision(accepted=all(rules.values()), rules=rules, reasons=reasons, table=rows, regressed=regressed)
