"""Clinic data access. Every query is scoped to a sandbox_id."""

import re
from datetime import datetime
from typing import Any

from app.clinic.models import (
    Appointment,
    AppointmentStatus,
    Escalation,
    Patient,
    Provider,
    Slot,
    SlotStatus,
)
from app.repo.store import DocumentStore

CLINIC_COLLECTIONS = ("patients", "providers", "slots", "appointments", "escalations")


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z ]", "", re.sub(r"\s+", " ", name.lower())).strip()


class ClinicRepository:
    def __init__(self, store: DocumentStore):
        self.store = store

    @property
    def backend(self) -> str:
        return self.store.backend

    # ------------------------------------------------------------ sandbox / seed

    async def reset_sandbox(self, sandbox_id: str) -> None:
        for coll in CLINIC_COLLECTIONS:
            await self.store.delete_many(coll, {"sandbox_id": sandbox_id})

    async def sandbox_exists(self, sandbox_id: str) -> bool:
        return await self.store.count("providers", {"sandbox_id": sandbox_id}) > 0

    async def bulk_insert(self, coll: str, models: list) -> None:
        await self.store.insert_many(coll, [m.model_dump() for m in models])

    # ------------------------------------------------------------ patients / providers

    async def find_patient(self, sandbox_id: str, full_name: str, dob: str) -> Patient | None:
        """Exact match on normalised full name + DOB. Returns None unless exactly one patient matches."""
        rows = await self.store.find("patients", {"sandbox_id": sandbox_id, "dob": dob})
        target = _norm_name(full_name)
        hits = [r for r in rows if _norm_name(f"{r['first_name']} {r['last_name']}") == target]
        return Patient(**hits[0]) if len(hits) == 1 else None

    async def get_patient(self, sandbox_id: str, patient_id: str) -> Patient | None:
        row = await self.store.find_one("patients", {"sandbox_id": sandbox_id, "id": patient_id})
        return Patient(**row) if row else None

    async def list_providers(self, sandbox_id: str, specialty: str | None = None) -> list[Provider]:
        flt: dict[str, Any] = {"sandbox_id": sandbox_id}
        if specialty:
            flt["specialty"] = specialty
        return [Provider(**r) for r in await self.store.find("providers", flt, sort=[("name", 1)])]

    async def get_provider(self, sandbox_id: str, provider_id: str) -> Provider | None:
        row = await self.store.find_one("providers", {"sandbox_id": sandbox_id, "id": provider_id})
        return Provider(**row) if row else None

    async def specialties(self, sandbox_id: str) -> list[str]:
        return sorted({p.specialty for p in await self.list_providers(sandbox_id)})

    # ------------------------------------------------------------ slots

    async def open_slots(
        self,
        sandbox_id: str,
        start: datetime,
        end: datetime,
        specialty: str | None = None,
        provider_id: str | None = None,
        limit: int = 0,
    ) -> list[Slot]:
        flt: dict[str, Any] = {
            "sandbox_id": sandbox_id,
            "status": SlotStatus.OPEN.value,
            "start": {"$gte": start, "$lt": end},
        }
        if specialty:
            flt["specialty"] = specialty
        if provider_id:
            flt["provider_id"] = provider_id
        rows = await self.store.find("slots", flt, sort=[("start", 1)], limit=limit)
        return [Slot(**r) for r in rows]

    async def get_slot(self, sandbox_id: str, slot_id: str) -> Slot | None:
        row = await self.store.find_one("slots", {"sandbox_id": sandbox_id, "id": slot_id})
        return Slot(**row) if row else None

    async def hold_slot(self, sandbox_id: str, slot_id: str, session_id: str) -> bool:
        """Atomic open -> held. False if someone else got there first."""
        return await self.store.update_one(
            "slots",
            {"sandbox_id": sandbox_id, "id": slot_id, "status": SlotStatus.OPEN.value},
            {"status": SlotStatus.HELD.value, "held_by": session_id},
        )

    async def release_slot(self, sandbox_id: str, slot_id: str, session_id: str) -> bool:
        return await self.store.update_one(
            "slots",
            {"sandbox_id": sandbox_id, "id": slot_id, "status": SlotStatus.HELD.value, "held_by": session_id},
            {"status": SlotStatus.OPEN.value, "held_by": None},
        )

    async def book_held_slot(self, sandbox_id: str, slot_id: str, session_id: str) -> bool:
        return await self.store.update_one(
            "slots",
            {"sandbox_id": sandbox_id, "id": slot_id, "status": SlotStatus.HELD.value, "held_by": session_id},
            {"status": SlotStatus.BOOKED.value, "held_by": None},
        )

    async def free_booked_slot(self, sandbox_id: str, slot_id: str) -> bool:
        return await self.store.update_one(
            "slots",
            {"sandbox_id": sandbox_id, "id": slot_id, "status": SlotStatus.BOOKED.value},
            {"status": SlotStatus.OPEN.value},
        )

    # ------------------------------------------------------------ appointments

    async def create_appointment(self, appt: Appointment) -> None:
        await self.store.insert_one("appointments", appt.model_dump())

    async def get_appointment(self, sandbox_id: str, appt_id: str) -> Appointment | None:
        row = await self.store.find_one("appointments", {"sandbox_id": sandbox_id, "id": appt_id})
        return Appointment(**row) if row else None

    async def patient_appointments(
        self, sandbox_id: str, patient_id: str, after: datetime | None = None
    ) -> list[Appointment]:
        flt: dict[str, Any] = {
            "sandbox_id": sandbox_id,
            "patient_id": patient_id,
            "status": AppointmentStatus.BOOKED.value,
        }
        if after:
            flt["start"] = {"$gte": after}
        rows = await self.store.find("appointments", flt, sort=[("start", 1)])
        return [Appointment(**r) for r in rows]

    async def all_appointments(self, sandbox_id: str) -> list[Appointment]:
        rows = await self.store.find("appointments", {"sandbox_id": sandbox_id}, sort=[("start", 1)])
        return [Appointment(**r) for r in rows]

    async def update_appointment(self, sandbox_id: str, appt_id: str, fields: dict) -> bool:
        return await self.store.update_one("appointments", {"sandbox_id": sandbox_id, "id": appt_id}, fields)

    # ------------------------------------------------------------ escalations

    async def add_escalation(self, esc: Escalation) -> None:
        await self.store.insert_one("escalations", esc.model_dump())

    async def escalations(self, sandbox_id: str, session_id: str | None = None) -> list[Escalation]:
        flt: dict[str, Any] = {"sandbox_id": sandbox_id}
        if session_id:
            flt["session_id"] = session_id
        return [Escalation(**r) for r in await self.store.find("escalations", flt)]

    # ------------------------------------------------------------ sessions / audit

    async def save_session(self, session: dict) -> None:
        if not await self.store.update_one("sessions", {"id": session["id"]}, session):
            await self.store.insert_one("sessions", session)

    async def get_session(self, session_id: str) -> dict | None:
        return await self.store.find_one("sessions", {"id": session_id})

    async def add_audit(self, entry: dict) -> None:
        await self.store.insert_one("audit_log", entry)

    async def audit_for_session(self, session_id: str) -> list[dict]:
        return await self.store.find("audit_log", {"session_id": session_id}, sort=[("seq", 1)])

    # ------------------------------------------------------------ mirrors of files (for browsing in Compass)

    async def upsert(self, coll: str, key: str, doc: dict) -> None:
        if not await self.store.update_one(coll, {key: doc[key]}, doc):
            await self.store.insert_one(coll, doc)

    # ------------------------------------------------------------ eval runs (mirror of reports/)

    async def save_eval_run(self, run: dict) -> None:
        if not await self.store.update_one("eval_runs", {"run_id": run["run_id"]}, run):
            await self.store.insert_one("eval_runs", run)

    async def list_eval_runs(self) -> list[dict]:
        return await self.store.find("eval_runs", {}, sort=[("created_at", -1)])

    async def get_eval_run(self, run_id: str) -> dict | None:
        return await self.store.find_one("eval_runs", {"run_id": run_id})
