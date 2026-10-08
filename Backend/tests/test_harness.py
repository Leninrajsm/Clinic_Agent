"""Eval harness end to end with fake models: a scripted good conversation must pass every check,
and a scripted bad one (claims success, never books) must fail the right checks."""

from types import SimpleNamespace

from app.db.seed import SeedOverrides
from app.evals.runner import run_trial
from app.evals.scenarios import load_scenarios
from app.policy.store import PolicyStore
from app.repo.clinic_repo import ClinicRepository
from app.repo.store import MemoryStore
from tests.conftest import RoutingLLM

SLOT = "slot_shah_20261015_0900"


def _book_simple():
    sc = load_scenarios(ids=["book_simple"])[0]
    return sc.model_copy(update={"seed": SeedOverrides(prefill_percent=0)})


def _rt(llm, settings):
    return SimpleNamespace(repo=ClinicRepository(MemoryStore()), llm=llm, settings=settings, policies=PolicyStore())


def test_all_scenarios_load_and_use_known_checks():
    from app.evals.checks import CHECKS
    from app.evals.judge import RUBRIC

    scenarios = load_scenarios()
    assert len(scenarios) == 21
    assert {s.split for s in scenarios} == {"train", "holdout"}
    for s in scenarios:
        assert all(c.type in CHECKS for c in s.checks), s.id
        assert all(r.id in RUBRIC for r in s.rubric), s.id


def test_alternatives_need_a_concrete_time():
    from app.evals.checks import _slot_time_tokens

    assert {"10:00", "10 am", "10am"} <= _slot_time_tokens("slot_mehta_20261019_1000")
    assert "2:30" in _slot_time_tokens("slot_miller_20261014_1430")


async def test_good_conversation_passes(settings):
    llm = RoutingLLM(
        agent=[
            "Sure! Could I have your full name and date of birth?",
            [("verify_patient", {"full_name": "Maria Lopez", "date_of_birth": "1988-03-14"})],
            [("find_slots", {"specialty": "dermatology", "date_from": "2026-10-15", "date_to": "2026-10-15"})],
            "Thanks Maria. I have 9:00 AM with Dr. Priya Shah on Thursday. Would that work?",
            [("hold_slot", {"slot_id": SLOT, "purpose": "book", "reason": "mole check"})],
            "To confirm: dermatology with Dr. Priya Shah, Thu Oct 15 at 9:00 AM. Shall I book it?",
            [("confirm_pending_action", {})],
            "You're booked. See you Thursday!",
        ],
        # Regression: the patient confirms AND ends in the same message (seen in the first real run).
        # That final "yes" must still reach the agent.
        simulator=["Maria Lopez, 1988-03-14", "9 works", "Yes please, go ahead. [END]"],
    )
    rt = _rt(llm, settings)
    res = await run_trial(rt, _book_simple(), "v1", "t", 1)
    assert res.status == "ok", res.error
    assert all(c["passed"] for c in res.checks), res.checks
    assert res.passed and res.score == 1.0
    assert res.ended_by == "patient"
    assert await rt.repo.store.count("slots", {"sandbox_id": "eval-t-book_simple-1"}) == 0  # sandbox cleaned


async def test_false_claim_conversation_fails_on_db_checks(settings):
    llm = RoutingLLM(
        agent=[
            [("verify_patient", {"full_name": "Maria Lopez", "date_of_birth": "1988-03-14"})],
            "All set, you're booked for Thursday at 9!",  # never searched, held or confirmed
            "You're welcome!",
        ],
        simulator=["Great, thanks [END]"],
    )
    res = await run_trial(_rt(llm, settings), _book_simple(), "v1", "t", 1)
    failed = {c["type"] for c in res.checks if not c["passed"]}
    assert "appointment_booked" in failed
    assert not res.passed and "appointment_booked" in res.critical_failures
    # the grounding check corrected the false claim before the patient saw it
    assert "grounding_correction" in res.flags


async def test_judge_blind_spot_is_covered(settings):
    """Judge gives 5/5 everywhere (it only reads the transcript), yet the trial fails on the DB check."""
    llm = RoutingLLM(
        agent=[[("verify_patient", {"full_name": "Maria Lopez", "date_of_birth": "1988-03-14"})],
               "Sorry, nothing is free on Thursday.", "Goodbye!"],
        simulator=["ok bye [END]"], judge_score=5,
    )
    res = await run_trial(_rt(llm, settings), _book_simple(), "v1", "t", 1)
    assert res.judge["normalized"] == 1.0
    assert not res.passed
