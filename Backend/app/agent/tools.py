"""Agent tools: declarations (what the model sees) and handlers (what actually happens).

Handlers run only after guards.check() passes. Note what is NOT a parameter anywhere:
patient_id. The patient is always taken from verified session state.
"""

from datetime import date, timedelta
from typing import Awaitable, Callable

from app.agent.context import ToolContext
from app.agent.guards import check
from app.agent.state import OfferedSlot, PendingAction, Stage
from app.clinic.dates import resolve_date
from app.clinic.models import Appointment, AppointmentStatus, Escalation, new_id
from app.db.seed import clinic_info, load_fixture
from app.llm.base import ToolSpec

MAX_SLOTS_RETURNED = 8
MAX_SLOTS_PER_DAY = 3


def _specialties() -> list[str]:
    return sorted({p["specialty"] for p in load_fixture()["providers"]})


def tool_specs() -> dict[str, ToolSpec]:
    clinic_topics = ["hours", "address", "phone", "providers", "new_patients",
                     "cancellation_policy", "insurance", "parking", "prescriptions"]
    specs = [
        ToolSpec("verify_patient",
                 "Verify the caller's identity using their full name and date of birth. Required before any "
                 "appointment lookup or change.",
                 {"type": "object", "properties": {
                     "full_name": {"type": "string", "description": "Patient's first and last name"},
                     "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"}},
                  "required": ["full_name", "date_of_birth"]}),
        ToolSpec("resolve_date",
                 "Convert a patient's date expression ('next Friday', 'tomorrow', 'Oct 16', 'next week') into exact "
                 "dates. Always use this instead of calculating dates yourself.",
                 {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
        ToolSpec("get_clinic_info", "Look up general clinic information.",
                 {"type": "object", "properties": {"topic": {"type": "string", "enum": clinic_topics}},
                  "required": ["topic"]}),
        ToolSpec("list_my_appointments", "List the verified patient's upcoming appointments.",
                 {"type": "object", "properties": {}}),
        ToolSpec("find_slots",
                 "Search open appointment slots by specialty or provider within a date range (inclusive).",
                 {"type": "object", "properties": {
                     "specialty": {"type": "string", "enum": _specialties()},
                     "provider_name": {"type": "string", "description": "Optional doctor's name, e.g. 'Dr. Shah'"},
                     "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                     "date_to": {"type": "string", "description": "YYYY-MM-DD (inclusive)"},
                     "time_of_day": {"type": "string", "enum": ["any", "morning", "afternoon"]}},
                  "required": ["date_from", "date_to"]}),
        ToolSpec("hold_slot",
                 "Temporarily hold a slot the patient chose, for a new booking or to reschedule an existing "
                 "appointment. Nothing is booked until confirm_pending_action.",
                 {"type": "object", "properties": {
                     "slot_id": {"type": "string"},
                     "purpose": {"type": "string", "enum": ["book", "reschedule"]},
                     "appointment_id": {"type": "string", "description": "Required when purpose is reschedule"},
                     "reason": {"type": "string", "description": "Short reason for visit, in the patient's words"}},
                  "required": ["slot_id", "purpose"]}),
        ToolSpec("request_cancellation",
                 "Prepare cancellation of one of the patient's appointments. Nothing changes until confirm_pending_action.",
                 {"type": "object", "properties": {"appointment_id": {"type": "string"}},
                  "required": ["appointment_id"]}),
        ToolSpec("confirm_pending_action",
                 "Commit the pending booking/reschedule/cancellation. Only after the patient explicitly agreed.",
                 {"type": "object", "properties": {}}),
        ToolSpec("discard_pending_action",
                 "Drop the pending action (patient declined or changed their mind) and release any held slot.",
                 {"type": "object", "properties": {}}),
        ToolSpec("escalate_to_human",
                 "Hand the conversation to clinic staff (patient asks for a person, request is out of scope, "
                 "new patient registration, or anything urgent).",
                 {"type": "object", "properties": {
                     "reason": {"type": "string"},
                     "urgency": {"type": "string", "enum": ["routine", "urgent", "emergency"]},
                     "summary": {"type": "string", "description": "One-line summary for staff"}},
                  "required": ["reason", "urgency"]}),
    ]
    return {s.name: s for s in specs}


# ---------------------------------------------------------------- handlers

async def _verify_patient(ctx: ToolContext, args: dict) -> dict:
    st = ctx.state
    st.verify_attempts += 1
    patient = await ctx.repo.find_patient(ctx.sandbox_id, args["full_name"], str(args["date_of_birth"]).strip())
    if patient:
        st.patient_id, st.patient_first_name, st.stage = patient.id, patient.first_name, Stage.VERIFIED
        return {"verified": True, "first_name": patient.first_name}
    remaining = ctx.settings.max_verification_attempts - st.verify_attempts
    if remaining <= 0:
        await _escalate(ctx, "Identity verification failed repeatedly", "routine", "", source="system")
        return {"verified": False, "locked": True,
                "instruction": "Verification failed too many times. Do not ask again. Tell the patient you could not "
                               "verify their identity and a staff member will call them back."}
    return {"verified": False, "attempts_remaining": remaining,
            "instruction": "No match. Do not say which detail was wrong; ask the patient to re-check both."}


async def _resolve_date(ctx: ToolContext, args: dict) -> dict:
    return resolve_date(str(args.get("text", "")), ctx.clock.today()).to_dict()


async def _get_clinic_info(ctx: ToolContext, args: dict) -> dict:
    topic = args.get("topic", "")
    if topic == "providers":
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return {"providers": [
            {"name": p["name"], "specialty": p["specialty"], "days": ", ".join(days[d] for d in p["weekdays"])}
            for p in load_fixture()["providers"]
        ]}
    info = clinic_info()
    return {topic: info[topic]} if topic in info else {"error": f"Unknown topic {topic!r}"}


async def _list_my_appointments(ctx: ToolContext, args: dict) -> dict:
    appts = await ctx.repo.patient_appointments(ctx.sandbox_id, ctx.state.patient_id, after=ctx.clock.now())
    out = []
    for a in appts:
        prov = await ctx.repo.get_provider(ctx.sandbox_id, a.provider_id)
        out.append({"appointment_id": a.id, "specialty": a.specialty, "provider": prov.name if prov else "",
                    "when": ctx.clock.fmt(a.start), "reason": a.reason})
    return {"appointments": out} if out else {"appointments": [], "message": "No upcoming appointments."}


async def _find_slots(ctx: ToolContext, args: dict) -> dict:
    d_from = max(date.fromisoformat(args["date_from"]), ctx.clock.today())
    d_to = date.fromisoformat(args.get("date_to") or args["date_from"])
    start = max(ctx.clock.at(d_from, 0), ctx.clock.now())
    end = ctx.clock.at(d_to + timedelta(days=1), 0)

    specialty = args.get("specialty") or None
    provider_id = None
    if name := (args.get("provider_name") or "").strip():
        key = name.lower().replace("dr.", "").replace("dr ", "").strip()
        matches = [p for p in await ctx.repo.list_providers(ctx.sandbox_id)
                   if key and (key in p.name.lower() or p.name.lower().split()[-1] in key)]
        if not matches:
            return {"error": f"No provider named {name!r}. Use get_clinic_info(topic='providers')."}
        provider_id = matches[0].id
        specialty = None

    slots = await ctx.repo.open_slots(ctx.sandbox_id, start, end, specialty=specialty, provider_id=provider_id)
    tod = args.get("time_of_day") or "any"
    if tod == "morning":
        slots = [s for s in slots if ctx.clock.local(s.start).hour < 12]
    elif tod == "afternoon":
        slots = [s for s in slots if ctx.clock.local(s.start).hour >= 12]

    # Spread results across days instead of returning one crowded morning.
    picked, per_day = [], {}
    for s in slots:
        day = ctx.clock.local(s.start).date()
        if per_day.get(day, 0) < MAX_SLOTS_PER_DAY:
            picked.append(s)
            per_day[day] = per_day.get(day, 0) + 1
        if len(picked) >= MAX_SLOTS_RETURNED:
            break

    names = {p.id: p.name for p in await ctx.repo.list_providers(ctx.sandbox_id)}
    result = []
    for s in picked:
        offered = OfferedSlot(slot_id=s.id, provider_name=names.get(s.provider_id, ""),
                              specialty=s.specialty, label=ctx.clock.fmt(s.start))
        ctx.state.offered_slots[s.id] = offered
        result.append(offered.model_dump())
    if not result:
        return {"slots": [], "message": "No open slots match this search."}
    return {"slots": result, "total_matching": len(slots)}


async def _hold_slot(ctx: ToolContext, args: dict) -> dict:
    st, slot_id = ctx.state, args["slot_id"]
    if not await ctx.repo.hold_slot(ctx.sandbox_id, slot_id, ctx.session.id):
        st.offered_slots.pop(slot_id, None)
        return {"error": "That slot was just taken. Offer the patient another option."}
    offered = st.offered_slots[slot_id]
    summary = f"{offered.specialty.title()} with {offered.provider_name}, {offered.label}"
    if args["purpose"] == "reschedule":
        old = await ctx.repo.get_appointment(ctx.sandbox_id, args["appointment_id"])
        summary = f"move {old.specialty} appointment from {ctx.clock.fmt(old.start)} to {offered.label} with {offered.provider_name}"
    st.pending = PendingAction(kind=args["purpose"], summary=summary, created_turn=st.turn, slot_id=slot_id,
                               appointment_id=args.get("appointment_id"), reason=args.get("reason") or "")
    st.stage = Stage.AWAITING_CONFIRMATION
    return {"held": True, "pending_summary": summary,
            "next_step": "Read these details back and ask the patient to confirm. Call confirm_pending_action only "
                         "after they explicitly agree in their next message."}


async def _request_cancellation(ctx: ToolContext, args: dict) -> dict:
    st = ctx.state
    appt = await ctx.repo.get_appointment(ctx.sandbox_id, args["appointment_id"])
    prov = await ctx.repo.get_provider(ctx.sandbox_id, appt.provider_id)
    summary = f"cancel {appt.specialty} appointment with {prov.name if prov else ''} on {ctx.clock.fmt(appt.start)}"
    st.pending = PendingAction(kind="cancel", summary=summary, created_turn=st.turn, appointment_id=appt.id)
    st.stage = Stage.AWAITING_CONFIRMATION
    return {"pending_summary": summary,
            "next_step": "Ask the patient to confirm the cancellation. Call confirm_pending_action only after they agree."}


async def _confirm_pending_action(ctx: ToolContext, args: dict) -> dict:
    st, p, sb = ctx.state, ctx.state.pending, ctx.sandbox_id
    if p.kind in ("book", "reschedule"):
        slot = await ctx.repo.get_slot(sb, p.slot_id)
        if not slot or not await ctx.repo.book_held_slot(sb, p.slot_id, ctx.session.id):
            st.pending, st.stage = None, Stage.VERIFIED
            return {"error": "The hold on that slot was lost. Search again and offer new options."}
        if p.kind == "book":
            appt_id = new_id("appt")
            await ctx.repo.create_appointment(Appointment(
                id=appt_id, sandbox_id=sb, patient_id=st.patient_id, provider_id=slot.provider_id,
                slot_id=slot.id, specialty=slot.specialty, start=slot.start, end=slot.end,
                reason=p.reason, created_by_session=ctx.session.id,
            ))
        else:
            appt_id = p.appointment_id
            old = await ctx.repo.get_appointment(sb, appt_id)
            await ctx.repo.free_booked_slot(sb, old.slot_id)
            await ctx.repo.update_appointment(sb, appt_id, {
                "slot_id": slot.id, "provider_id": slot.provider_id, "specialty": slot.specialty,
                "start": slot.start, "end": slot.end, "rescheduled_from_slot": old.slot_id,
            })
        status = "booked" if p.kind == "book" else "rescheduled"
    else:
        appt_id = p.appointment_id
        appt = await ctx.repo.get_appointment(sb, appt_id)
        await ctx.repo.update_appointment(sb, appt_id, {"status": AppointmentStatus.CANCELLED.value})
        await ctx.repo.free_booked_slot(sb, appt.slot_id)
        status = "cancelled"

    done = f"{status}: {p.summary}"
    st.completed.append(done)
    ctx.committed_this_turn.append(done)
    st.pending, st.stage, st.offered_slots = None, Stage.VERIFIED, {}
    return {"status": status, "appointment_id": appt_id, "details": p.summary}


async def _discard_pending_action(ctx: ToolContext, args: dict) -> dict:
    st = ctx.state
    if st.pending.slot_id:
        await ctx.repo.release_slot(ctx.sandbox_id, st.pending.slot_id, ctx.session.id)
    dropped = st.pending.summary
    st.pending, st.stage = None, Stage.VERIFIED
    return {"discarded": dropped}


async def _escalate(ctx: ToolContext, reason: str, urgency: str, summary: str, source: str = "agent") -> None:
    st = ctx.state
    if st.pending and st.pending.slot_id:
        await ctx.repo.release_slot(ctx.sandbox_id, st.pending.slot_id, ctx.session.id)
    st.pending = None
    await ctx.repo.add_escalation(Escalation(
        sandbox_id=ctx.sandbox_id, session_id=ctx.session.id, patient_id=st.patient_id, reason=reason,
        urgency=urgency, summary=summary, source=source, created_at=ctx.clock.now(),
    ))
    st.stage, st.escalation_reason = Stage.ESCALATED, reason


async def _escalate_to_human(ctx: ToolContext, args: dict) -> dict:
    await _escalate(ctx, args["reason"], args["urgency"], args.get("summary", ""))
    return {"escalated": True,
            "message": "Clinic staff have been notified and will follow up with the patient."}


HANDLERS: dict[str, Callable[[ToolContext, dict], Awaitable[dict]]] = {
    "verify_patient": _verify_patient,
    "resolve_date": _resolve_date,
    "get_clinic_info": _get_clinic_info,
    "list_my_appointments": _list_my_appointments,
    "find_slots": _find_slots,
    "hold_slot": _hold_slot,
    "request_cancellation": _request_cancellation,
    "confirm_pending_action": _confirm_pending_action,
    "discard_pending_action": _discard_pending_action,
    "escalate_to_human": _escalate_to_human,
}


async def execute_tool(name: str, args: dict, ctx: ToolContext) -> tuple[dict, str | None]:
    """Run one tool call through the guard layer. Returns (result, denied_by_guard_or_None)."""
    if name not in HANDLERS:
        return {"error": f"Unknown tool {name!r}."}, "unknown_tool"
    denial = await check(name, args, ctx)
    if denial:
        return denial.to_result(), denial.guard
    try:
        if ctx.faults.get(name, 0) > 0:  # fault injection used by eval scenarios
            ctx.faults[name] -= 1
            raise TimeoutError(f"{name} timed out")
        return await HANDLERS[name](ctx, args), None
    except Exception as exc:  # a broken tool must never crash the conversation
        return {"error": f"{name} failed ({type(exc).__name__}); the scheduling system may be temporarily "
                         "unavailable. Do not guess results."}, None


async def system_escalate(ctx: ToolContext, reason: str, urgency: str) -> None:
    """Escalation forced by code (safety pre-check), not chosen by the model."""
    await _escalate(ctx, reason, urgency, "", source="system")
