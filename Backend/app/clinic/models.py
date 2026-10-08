"""Clinic domain models. All records carry a sandbox_id so eval runs never touch each other."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Doc(BaseModel):
    # Store enums as plain strings so both MongoDB and the memory store compare them the same way.
    model_config = ConfigDict(use_enum_values=True, validate_default=True, validate_assignment=True)


class Patient(Doc):
    id: str
    sandbox_id: str
    first_name: str
    last_name: str
    dob: str  # ISO date, e.g. "1988-03-14" (kept as a string: BSON has no date-only type)
    phone: str


class Provider(Doc):
    id: str
    sandbox_id: str
    name: str
    specialty: str


class SlotStatus(str, Enum):
    OPEN = "open"
    HELD = "held"
    BOOKED = "booked"


class Slot(Doc):
    id: str
    sandbox_id: str
    provider_id: str
    specialty: str
    start: datetime
    end: datetime
    status: SlotStatus = SlotStatus.OPEN
    held_by: str | None = None  # session id holding the slot


class AppointmentStatus(str, Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


class Appointment(Doc):
    id: str
    sandbox_id: str
    patient_id: str
    provider_id: str
    slot_id: str
    specialty: str
    start: datetime
    end: datetime
    reason: str = ""
    status: AppointmentStatus = AppointmentStatus.BOOKED
    created_by_session: str | None = None
    rescheduled_from_slot: str | None = None


class Urgency(str, Enum):
    ROUTINE = "routine"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class Escalation(Doc):
    id: str = Field(default_factory=lambda: new_id("esc"))
    sandbox_id: str
    session_id: str
    patient_id: str | None = None
    reason: str
    urgency: Urgency
    summary: str = ""
    source: str = "agent"  # "agent" (LLM chose to) or "system" (code forced it)
    created_at: datetime
