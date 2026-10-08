"""Session state: the code-owned source of truth for where the conversation is.

The model never decides who the patient is or whether something was booked; it reads this
state (rendered into the prompt) and can only change it through guarded tools.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.clinic.models import new_id


class Stage(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    ESCALATED = "escalated"


ALWAYS = {"get_clinic_info", "resolve_date", "escalate_to_human"}

TOOLS_BY_STAGE: dict[Stage, set[str]] = {
    Stage.UNVERIFIED: ALWAYS | {"verify_patient"},
    Stage.VERIFIED: ALWAYS | {"list_my_appointments", "find_slots", "hold_slot", "request_cancellation"},
    Stage.AWAITING_CONFIRMATION: ALWAYS | {
        "list_my_appointments", "find_slots", "confirm_pending_action", "discard_pending_action",
    },
    Stage.ESCALATED: {"get_clinic_info"},
}


class OfferedSlot(BaseModel):
    slot_id: str
    provider_name: str
    specialty: str
    label: str  # "Fri Oct 16, 9:00 AM"


class PendingAction(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pend"))
    kind: Literal["book", "reschedule", "cancel"]
    summary: str
    created_turn: int
    slot_id: str | None = None
    appointment_id: str | None = None
    reason: str = ""


class SessionState(BaseModel):
    stage: Stage = Stage.UNVERIFIED
    turn: int = 0
    patient_id: str | None = None
    patient_first_name: str | None = None
    verify_attempts: int = 0
    offered_slots: dict[str, OfferedSlot] = {}
    pending: PendingAction | None = None
    completed: list[str] = []
    escalation_reason: str | None = None
    audit_seq: int = 0

    def allowed_tools(self) -> set[str]:
        return TOOLS_BY_STAGE[self.stage]

    def summary(self, max_attempts: int) -> str:
        lines: list[str] = []
        if self.stage == Stage.ESCALATED:
            lines.append(f"- ESCALATED to clinic staff: {self.escalation_reason}. Do not schedule anything further; "
                         "tell the patient a staff member will follow up and answer only general clinic questions.")
        if self.patient_id:
            lines.append(f"- Identity: VERIFIED. Patient first name: {self.patient_first_name}. Do not ask for identity again.")
        else:
            lines.append(f"- Identity: NOT verified ({self.verify_attempts}/{max_attempts} attempts used). "
                         "No appointment information or actions until verified.")
        if self.offered_slots:
            lines.append("- Slots found so far (only these slot_ids can be held):")
            lines += [f"    {s.slot_id}: {s.specialty}, {s.provider_name}, {s.label}" for s in self.offered_slots.values()]
        if self.pending:
            lines.append(f"- PENDING ACTION awaiting the patient's explicit confirmation: {self.pending.kind} -> "
                         f"{self.pending.summary}. Confirm only if the patient's latest message clearly agrees; "
                         "if they decline or change their mind, discard it.")
        if self.completed:
            lines.append("- Completed in this conversation: " + "; ".join(self.completed))
        return "\n".join(lines)


class TranscriptTurn(BaseModel):
    role: Literal["patient", "agent"]
    text: str
    turn: int


class Session(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sess"))
    sandbox_id: str
    policy_version: str
    created_at: datetime
    state: SessionState = SessionState()
    transcript: list[TranscriptTurn] = []
