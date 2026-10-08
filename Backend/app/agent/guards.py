"""Code-enforced rules checked before every tool call.

These are the safety properties that must hold regardless of what the prompt/policy says,
which is why the improvement loop can never edit them:
  * a tool must be allowed in the current stage (e.g. nothing patient-specific before verification)
  * identity comes from session state, never from model-supplied arguments
  * only slots this session actually found can be held (no invented slot ids)
  * patients can only act on their own appointments
  * a commit needs a patient message between the hold and the confirm (consent)
  * search windows are bounded and never in the past
"""

from dataclasses import dataclass
from datetime import date

from app.agent.context import ToolContext
from app.clinic.models import AppointmentStatus


@dataclass
class Denial:
    guard: str
    message: str

    def to_result(self) -> dict:
        return {"error": self.message, "denied_by_guard": self.guard}


def _parse_date(value: str | None, field: str) -> date | Denial:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return Denial("invalid_date", f"{field} must be YYYY-MM-DD (use resolve_date first). Got: {value!r}")


async def _own_future_appointment(ctx: ToolContext, appointment_id: str | None) -> Denial | None:
    if not appointment_id:
        return Denial("missing_appointment", "appointment_id is required. Use list_my_appointments to find it.")
    appt = await ctx.repo.get_appointment(ctx.sandbox_id, appointment_id)
    # Same message whether it doesn't exist or belongs to someone else: never leak other patients' data.
    if appt is None or appt.patient_id != ctx.state.patient_id:
        return Denial("not_patients_appointment", "No appointment with that id for this patient.")
    if appt.status != AppointmentStatus.BOOKED.value or appt.start <= ctx.clock.now():
        return Denial("appointment_not_changeable", "That appointment is cancelled or in the past.")
    return None


async def check(tool: str, args: dict, ctx: ToolContext) -> Denial | None:
    st = ctx.state

    if tool not in st.allowed_tools():
        return Denial(
            "tool_not_allowed_in_stage",
            f"'{tool}' is not available at this point (stage: {st.stage.value}). "
            + ("Verify the patient's identity first." if not st.patient_id else ""),
        )

    if tool == "verify_patient":
        if st.verify_attempts >= ctx.settings.max_verification_attempts:
            return Denial("verification_locked", "Verification attempts exhausted. Do not retry.")
        if not args.get("full_name") or not args.get("date_of_birth"):
            return Denial("missing_fields", "Both full_name and date_of_birth (YYYY-MM-DD) are required.")

    elif tool == "find_slots":
        d_from = _parse_date(args.get("date_from"), "date_from")
        if isinstance(d_from, Denial):
            return d_from
        d_to = _parse_date(args.get("date_to") or args.get("date_from"), "date_to")
        if isinstance(d_to, Denial):
            return d_to
        today = ctx.clock.today()
        if d_to < today:
            return Denial("past_dates", f"That range is in the past. Today is {today.isoformat()}.")
        if d_to < d_from:
            return Denial("bad_range", "date_to is before date_from.")
        if (d_to - max(d_from, today)).days > ctx.settings.max_search_window_days:
            return Denial("window_too_large", f"Search at most {ctx.settings.max_search_window_days} days at a time.")
        if not args.get("specialty") and not args.get("provider_name"):
            return Denial("missing_filter", "Provide a specialty or a provider_name.")

    elif tool == "hold_slot":
        if st.pending:
            return Denial("pending_exists", "Another action is pending. Confirm or discard it first.")
        if args.get("slot_id") not in st.offered_slots:
            return Denial("slot_not_offered", "Unknown slot_id. Only slots returned by find_slots in this conversation can be held.")
        if args.get("purpose") == "reschedule":
            return await _own_future_appointment(ctx, args.get("appointment_id"))

    elif tool == "request_cancellation":
        if st.pending:
            return Denial("pending_exists", "Another action is pending. Confirm or discard it first.")
        return await _own_future_appointment(ctx, args.get("appointment_id"))

    elif tool == "confirm_pending_action":
        if not st.pending:
            return Denial("nothing_pending", "There is no pending action to confirm.")
        if st.pending.created_turn >= st.turn:
            return Denial(
                "confirmation_requires_patient_reply",
                "You cannot confirm in the same turn you created the pending action. Read back the details "
                "and wait for the patient to explicitly agree.",
            )

    elif tool == "discard_pending_action":
        if not st.pending:
            return Denial("nothing_pending", "There is no pending action to discard.")

    elif tool == "escalate_to_human":
        if args.get("urgency") not in ("routine", "urgent", "emergency"):
            return Denial("bad_urgency", "urgency must be routine, urgent or emergency.")

    return None
