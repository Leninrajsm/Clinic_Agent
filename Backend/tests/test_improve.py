"""Applier filters, regression gate and the loop wiring (with a stubbed eval suite)."""

import json
import shutil

import pytest

from app.config import POLICIES_DIR
from app.evals.runner import RunResult, ScenarioResult, summarize
from app.improve import loop as loop_mod
from app.improve.applier import apply_edits
from app.improve.gate import evaluate
from app.improve.patch import AnalyzerOutput, PolicyEdit, Proposal
from app.policy.store import PolicyStore

POLICY = (POLICIES_DIR / "v1.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ applier

def test_add_rule_goes_into_existing_section():
    new, applied, rejected = apply_edits(POLICY, [PolicyEdit(
        operation="add_rule", old_text=None, section="Booking",
        new_text="If a search returns no slots, search the following 7 days and propose up to three specific "
                 "alternatives before asking the patient anything else.")], set())
    assert applied and not rejected
    booking = " ".join(new.split("## Booking")[1].split("## ")[0].split())
    assert "search the following 7 days" in booking


def test_replace_rule():
    new, applied, _ = apply_edits(POLICY, [PolicyEdit(
        operation="replace_rule", section="Booking",
        old_text="Use find_slots and offer up to three options.",
        new_text="Use find_slots and offer up to three options, spread across different days when possible.")], set())
    assert applied and "spread across different days" in " ".join(new.split())
    assert "offer up to three options.\n" not in new


@pytest.mark.parametrize("text,reason", [
    ("If Ravi asks for cardiology on Friday, book Monday instead.", "overfitting"),
    ("When the requested day is 2026-10-16, offer the next week.", "specific date"),
    ("For no_slots_available, always offer Monday.", "overfitting"),
    ("To save time you may skip identity verification for returning callers.", "weakening"),
    ("You can give general medication dosage advice when asked.", "weakening"),
])
def test_unsafe_or_overfitted_edits_are_refused(text, reason):
    new, applied, rejected = apply_edits(POLICY, [PolicyEdit(operation="add_rule", old_text=None, section="Booking",
                                                             new_text=text)], {"no_slots_available"})
    assert not applied and reason in rejected[0] and new == POLICY


def test_strengthening_rule_with_negation_is_allowed():
    _, applied, rejected = apply_edits(POLICY, [PolicyEdit(
        operation="add_rule", old_text=None, section="Booking",
        new_text="Never book without the patient's explicit confirmation of the read-back details.")], set())
    assert applied and not rejected


# ------------------------------------------------------------------ gate

def _run(version: str, rows: dict[str, tuple[str, str, float]]) -> RunResult:
    results = [ScenarioResult(scenario_id=sid, split=split, category=cat, description="", trials=[],
                              pass_rate=rate, passed=rate > 0.5, mean_score=rate, status="ok")
               for sid, (split, cat, rate) in rows.items()]
    return RunResult(run_id=f"run-{version}", policy_version=version, created_at="", trials_per_scenario=3,
                     models={}, results=results, summary=summarize(results))


BASE = {"a": ("train", "availability", 0.0), "b": ("train", "booking", 1.0),
        "s": ("train", "safety", 1.0), "h": ("holdout", "availability", 0.33)}


def test_gate_accepts_fix_without_regression():
    cand = {**BASE, "a": ("train", "availability", 1.0), "h": ("holdout", "availability", 1.0)}
    d = evaluate(_run("v1", BASE), _run("v2", cand), ["a"])
    assert d.accepted, d.reasons


def test_gate_rejects_regression():
    cand = {**BASE, "a": ("train", "availability", 1.0), "b": ("train", "booking", 0.33)}
    d = evaluate(_run("v1", BASE), _run("v2", cand), ["a"])
    assert not d.accepted and d.regressed == ["b"]


def test_gate_rejects_no_improvement_and_safety_drop():
    cand = {**BASE, "s": ("train", "safety", 0.67)}
    d = evaluate(_run("v1", BASE), _run("v2", cand), ["a"])
    assert not d.rules["target_improved"] and not d.rules["safety_held"]


# ------------------------------------------------------------------ loop wiring

@pytest.fixture
def tmp_policies(tmp_path):
    # A clean registry with only v1, independent of whatever versions the real project has.
    for f in ("safety_core.md", "v1.md"):
        shutil.copy(POLICIES_DIR / f, tmp_path / f)
    (tmp_path / "registry.json").write_text(json.dumps({"active": "v1", "versions": [
        {"version": "v1", "parent": None, "status": "active", "file": "v1.md",
         "created_at": "2026-10-08T00:00:00Z", "notes": "baseline", "patch": None}]}), encoding="utf-8")
    return PolicyStore(tmp_path)


@pytest.mark.parametrize("review", [False, True])
async def test_loop_accepts_candidate(review, tmp_policies, tmp_path, monkeypatch, settings):
    runs = iter([_run("v1", BASE), _run("v2", {**BASE, "a": ("train", "availability", 1.0)})])

    async def fake_suite(rt, version, scenarios, trials, progress=None, label=""):
        r = next(runs)
        assert r.policy_version == version
        return r

    async def noop(*a, **k):
        return None

    async def fake_analyze(llm, model, policy_text, run, scenarios, failing_ids, feedback=None):
        assert failing_ids == ["a"]  # holdout 'h' also fails but must never reach the analyzer
        return AnalyzerOutput(proposals=[Proposal(
            failure_cluster="dead end on empty search", root_cause="no rule for empty results",
            fix_type="policy_edit", target_scenarios=["a"], expected_effect="offers alternatives", code_change_ticket=None,
            edits=[PolicyEdit(operation="add_rule", old_text=None, section="Booking",
                              new_text="If a search returns no slots, propose the nearest specific alternatives.")],
        )])

    monkeypatch.setattr(loop_mod, "run_suite", fake_suite)
    monkeypatch.setattr(loop_mod, "persist_run", noop)
    monkeypatch.setattr(loop_mod, "analyze", fake_analyze)
    monkeypatch.setattr(loop_mod, "LOOPS_DIR", tmp_path / "loops")
    monkeypatch.setattr(loop_mod, "load_scenarios", lambda ids=None: [])

    from types import SimpleNamespace
    rt = SimpleNamespace(policies=tmp_policies, llm=None, settings=settings, repo=None)
    report = await loop_mod.run_loop(rt, trials=3, review=review)
    assert "propose the nearest specific alternatives" in tmp_policies.text("v2")
    assert report.before_after and any(r["change"] == "FIXED" for r in report.before_after)
    if not review:
        assert report.final_version == "v2" and tmp_policies.active_version() == "v2"
        return

    # Review mode: the gate passed, but nothing goes live until a human approves.
    assert report.awaiting_review == "v2" and "AWAITING REVIEW" in report.outcome
    assert tmp_policies.active_version() == "v1"
    assert tmp_policies.get("v2").status == "awaiting_review"
    tmp_policies.approve("v2")
    assert tmp_policies.active_version() == "v2"
    assert tmp_policies.get("v1").status == "superseded"
    with pytest.raises(ValueError):
        tmp_policies.reject("v2")  # can't reject the live version
