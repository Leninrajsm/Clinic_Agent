"""Eval run reports: full JSON (with transcripts and tool traces) + a readable markdown summary.
Committed to the repo so a reviewer can see real results without running anything."""

import json

from app.config import REPORTS_DIR
from app.evals.runner import RunResult, ScenarioResult

RUNS_DIR = REPORTS_DIR / "runs"


def _pct(r: ScenarioResult) -> str:
    valid = [t for t in r.trials if t.status == "ok"]
    return f"{sum(t.passed for t in valid)}/{len(valid)}" + (f" (+{len(r.trials) - len(valid)} err)" if len(valid) < len(r.trials) else "")


def failing_details(r: ScenarioResult) -> list[str]:
    lines = []
    for t in r.trials:
        if t.status == "error":
            lines.append(f"  - trial {t.trial}: ERROR {t.error}")
        elif not t.passed:
            failed = [f"{c['type']} ({c['detail']})" for c in t.checks if not c["passed"]]
            low = [f"{s['id']}={s['score']} ({s['reason']})" for s in t.judge.get("scores", []) if not s["passed"]]
            lines.append(f"  - trial {t.trial}: score {t.score}; failed checks: {failed or 'none'}; "
                         f"low rubric: {low or 'none'}")
    return lines


def render_markdown(run: RunResult) -> str:
    s = run.summary
    out = [
        f"# Eval run `{run.run_id}`",
        "",
        f"- Policy: **{run.policy_version}**  |  trials per scenario: {run.trials_per_scenario}  |  {run.created_at}",
        f"- Models: {run.models}",
        f"- **Overall: {s['overall']['passed']}/{s['overall']['total']} scenarios passed** "
        f"(train {s['train']['passed']}/{s['train']['total']}, holdout {s['holdout']['passed']}/{s['holdout']['total']}); "
        f"mean score {s['overall']['mean_score']}",
        f"- Errored trials (infrastructure, excluded from pass rates): {s['error_trials']}",
        "",
        "| Scenario | Split | Category | Trials passed | Mean score | Result |",
        "|---|---|---|---|---|---|",
    ]
    for r in run.results:
        verdict = "ERROR" if r.status == "error" else ("PASS" if r.passed else "FAIL")
        out.append(f"| {r.scenario_id} | {r.split} | {r.category} | {_pct(r)} | {r.mean_score} | {verdict} |")
    failures = [r for r in run.results if not r.passed]
    if failures:
        out += ["", "## Failures", ""]
        for r in failures:
            out.append(f"**{r.scenario_id}**: {r.description}")
            out += failing_details(r)
            sample = next((t for t in r.trials if t.status == "ok" and not t.passed), None)
            if sample:
                out += ["", "<details><summary>Sample transcript</summary>", "", "```"]
                out += [f"{'PATIENT' if m['role'] == 'patient' else 'AGENT  '}: {m['text']}" for m in sample.transcript]
                out += ["```", "", "</details>", ""]
    return "\n".join(out) + "\n"


def save_run(run: RunResult) -> tuple[str, str]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    jpath, mpath = RUNS_DIR / f"{run.run_id}.json", RUNS_DIR / f"{run.run_id}.md"
    jpath.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    mpath.write_text(render_markdown(run), encoding="utf-8")
    return str(jpath), str(mpath)


async def persist_run(repo, run: RunResult) -> None:
    """Files are the source of truth (committed to git); MongoDB gets a copy for browsing in Compass."""
    save_run(run)
    try:
        await repo.save_eval_run(run.model_dump(mode="json"))
    except Exception:  # read-only DB user or document too large: the file copy is enough
        pass


def load_run(run_id: str) -> RunResult:
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No saved run {run_id!r} in {RUNS_DIR}")
    return RunResult.model_validate_json(path.read_text(encoding="utf-8"))


def list_runs() -> list[dict]:
    if not RUNS_DIR.exists():
        return []
    out = []
    for p in sorted(RUNS_DIR.glob("*.json"), reverse=True):
        data = json.loads(p.read_text(encoding="utf-8"))
        out.append({"run_id": data["run_id"], "policy_version": data["policy_version"],
                    "created_at": data["created_at"], "trials_per_scenario": data["trials_per_scenario"],
                    "summary": data["summary"]})
    return out
