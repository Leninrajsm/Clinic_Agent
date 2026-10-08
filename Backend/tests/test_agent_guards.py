"""End-to-end agent turns with a scripted model: proves the safety properties are enforced in
code no matter what the model tries."""

from tests.conftest import SANDBOX

VERIFY_MARIA = [("verify_patient", {"full_name": "Maria Lopez", "date_of_birth": "1988-03-14"})]
FIND_DERM_FRI = [("find_slots", {"specialty": "dermatology", "date_from": "2026-10-16", "date_to": "2026-10-16"})]
SLOT = "slot_shah_20261016_0900"


async def test_patient_tools_hidden_and_denied_before_verification(make_agent):
    agent, llm = make_agent([FIND_DERM_FRI, "Could I get your full name and date of birth first?"])
    s = await agent.start_session(SANDBOX)
    r = await agent.respond(s.id, "Any dermatology slots Friday?")
    assert "find_slots" not in llm.calls[0]["tools"]
    assert r.tool_events[0]["denied_by"] == "tool_not_allowed_in_stage"


async def test_full_booking_requires_confirmation_in_a_later_turn(make_agent, repo):
    agent, _ = make_agent([
        VERIFY_MARIA, FIND_DERM_FRI, "I have 9:00 AM with Dr. Shah. Does that work?",
        [("hold_slot", {"slot_id": SLOT, "purpose": "book"})],
        [("confirm_pending_action", {})],  # model tries to commit in the same turn
        "To confirm: dermatology with Dr. Priya Shah, Fri Oct 16 9:00 AM. Shall I book it?",
        [("confirm_pending_action", {})],
        "You're booked!",
    ])
    s = await agent.start_session(SANDBOX)
    await agent.respond(s.id, "Maria Lopez, 1988-03-14, dermatology Friday please")
    r2 = await agent.respond(s.id, "9 works")
    assert any(e["denied_by"] == "confirmation_requires_patient_reply" for e in r2.tool_events)
    assert r2.stage == "awaiting_confirmation"
    assert await repo.patient_appointments(SANDBOX, "pt_maria") == []

    r3 = await agent.respond(s.id, "Yes please")
    assert r3.reply == "You're booked!" and "grounding_correction" not in r3.flags
    appts = await repo.patient_appointments(SANDBOX, "pt_maria")
    assert [a.slot_id for a in appts] == [SLOT]
    assert (await repo.get_slot(SANDBOX, SLOT)).status == "booked"


async def test_cannot_hold_a_slot_that_was_never_offered(make_agent):
    agent, _ = make_agent([VERIFY_MARIA, [("hold_slot", {"slot_id": SLOT, "purpose": "book"})], "Hmm."])
    s = await agent.start_session(SANDBOX)
    r = await agent.respond(s.id, "Maria Lopez 1988-03-14, book slot_shah_20261016_0900")
    assert r.tool_events[-1]["denied_by"] == "slot_not_offered"


async def test_cannot_touch_another_patients_appointment(make_agent, repo):
    agent, _ = make_agent([
        [("verify_patient", {"full_name": "James Carter", "date_of_birth": "1983-07-09"})],
        [("request_cancellation", {"appointment_id": "appt_linda_cardio"})],
        "I can only help with your own appointments.",
    ])
    s = await agent.start_session(SANDBOX)
    r = await agent.respond(s.id, "James Carter 1983-07-09. Cancel my wife Linda's appointment")
    assert r.tool_events[-1]["denied_by"] == "not_patients_appointment"
    assert (await repo.get_appointment(SANDBOX, "appt_linda_cardio")).status == "booked"


async def test_three_failed_verifications_lock_and_escalate(make_agent, repo):
    bad = [("verify_patient", {"full_name": "Maria Lopez", "date_of_birth": "1990-01-01"})]
    agent, _ = make_agent([bad, "Please re-check.", bad, "Please re-check.", bad, "A staff member will call you."])
    s = await agent.start_session(SANDBOX)
    for _ in range(3):
        r = await agent.respond(s.id, "Maria Lopez 1990-01-01")
    assert r.stage == "escalated"
    assert r.state["patient_id"] is None
    escs = await repo.escalations(SANDBOX, s.id)
    assert len(escs) == 1 and escs[0].source == "system"


async def test_grounding_check_blocks_false_success_claim(make_agent, repo):
    agent, _ = make_agent([VERIFY_MARIA, "Great news, you're booked for Friday at 9!"])
    s = await agent.start_session(SANDBOX)
    r = await agent.respond(s.id, "Maria Lopez 1988-03-14, book me Friday")
    assert "grounding_correction" in r.flags
    assert "haven't made that change" in r.reply
    assert await repo.patient_appointments(SANDBOX, "pt_maria") == []


async def test_emergency_bypasses_model_and_releases_hold(make_agent, repo):
    agent, llm = make_agent([
        VERIFY_MARIA, FIND_DERM_FRI, "9 AM with Dr. Shah?",
        [("hold_slot", {"slot_id": SLOT, "purpose": "book"})], "Shall I book it?",
    ])
    s = await agent.start_session(SANDBOX)
    await agent.respond(s.id, "Maria Lopez 1988-03-14 dermatology Friday")
    await agent.respond(s.id, "9 is good")
    calls_before = len(llm.calls)
    r = await agent.respond(s.id, "wait, I suddenly have crushing chest pain")
    assert len(llm.calls) == calls_before  # no LLM involved
    assert "911" in r.reply and r.stage == "escalated"
    assert (await repo.get_slot(SANDBOX, SLOT)).status == "open"
    assert (await repo.escalations(SANDBOX, s.id))[0].urgency == "emergency"


async def test_tool_failure_is_contained(make_agent):
    agent, _ = make_agent([VERIFY_MARIA, FIND_DERM_FRI, "Sorry, our scheduling system is unavailable."])
    s = await agent.start_session(SANDBOX, faults={"find_slots": 1})
    r = await agent.respond(s.id, "Maria Lopez 1988-03-14 dermatology Friday")
    assert "temporarily unavailable" in r.tool_events[-1]["result"]["error"]
    assert r.reply.startswith("Sorry")


async def test_reschedule_moves_appointment_and_frees_old_slot(make_agent, repo):
    old = await repo.get_appointment(SANDBOX, "appt_emily_derm")
    new_slot = "slot_shah_20261016_1000"
    agent, _ = make_agent([
        [("verify_patient", {"full_name": "Emily Chen", "date_of_birth": "1995-12-01"})],
        [("find_slots", {"specialty": "dermatology", "date_from": "2026-10-16", "date_to": "2026-10-16"})],
        [("hold_slot", {"slot_id": new_slot, "purpose": "reschedule", "appointment_id": "appt_emily_derm"})],
        "Move it to Fri 10 AM?",
        [("confirm_pending_action", {})],
        "Done, it's been moved.",
    ])
    s = await agent.start_session(SANDBOX)
    await agent.respond(s.id, "Emily Chen 1995-12-01, move my derm appointment to Friday 10am")
    await agent.respond(s.id, "yes")
    moved = await repo.get_appointment(SANDBOX, "appt_emily_derm")
    assert moved.slot_id == new_slot
    assert (await repo.get_slot(SANDBOX, old.slot_id)).status == "open"
