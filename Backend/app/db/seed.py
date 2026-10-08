"""Seeds a sandbox with the synthetic clinic.

Slots are generated relative to the clock's "today", so the same fixture works for the live
demo (real clock) and for evals (frozen clock). Scenarios pass overrides to create specific
situations, e.g. "cardiology fully booked on Friday" or "Dr. Mehta on leave".
"""

import hashlib
import json
from datetime import date, datetime, timedelta
from functools import lru_cache

from pydantic import BaseModel

from app.clinic.dates import Clock
from app.clinic.models import Appointment, Patient, Provider, Slot, SlotStatus
from app.config import FIXTURES_DIR
from app.repo.clinic_repo import ClinicRepository


class DayFill(BaseModel):
    date: str  # ISO date
    specialty: str | None = None
    provider_id: str | None = None


class Leave(BaseModel):
    provider_id: str
    date_from: str
    date_to: str


class FixtureAppointment(BaseModel):
    id: str
    patient_id: str
    provider_id: str
    time: str  # "HH:MM"
    day_offset: int | None = None  # next working day of the provider on/after today+offset
    date: str | None = None  # or an explicit ISO date
    reason: str = ""


class SeedOverrides(BaseModel):
    fill_days: list[DayFill] = []
    provider_leave: list[Leave] = []
    extra_appointments: list[FixtureAppointment] = []
    prefill_percent: int | None = None


@lru_cache
def load_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "clinic_seed.json").read_text(encoding="utf-8"))


def clinic_info() -> dict:
    return load_fixture()["clinic"]


def _prefilled(provider_id: str, start: datetime, percent: int) -> bool:
    """Deterministic 'other patients already booked this' so availability looks realistic."""
    h = int(hashlib.md5(f"{provider_id}|{start.isoformat()}".encode()).hexdigest(), 16)
    return h % 100 < percent


def _on_leave(provider_id: str, d: date, leave: list[Leave]) -> bool:
    return any(
        l.provider_id == provider_id and date.fromisoformat(l.date_from) <= d <= date.fromisoformat(l.date_to)
        for l in leave
    )


async def seed_sandbox(
    repo: ClinicRepository,
    sandbox_id: str,
    clock: Clock,
    overrides: SeedOverrides | None = None,
) -> dict:
    fx = load_fixture()
    ov = overrides or SeedOverrides()
    now, today = clock.now(), clock.today()
    step = timedelta(minutes=fx["slot_minutes"])
    prefill = fx["prefill_percent"] if ov.prefill_percent is None else ov.prefill_percent

    await repo.reset_sandbox(sandbox_id)

    patients = [Patient(sandbox_id=sandbox_id, **p) for p in fx["patients"]]
    providers = [
        Provider(sandbox_id=sandbox_id, id=p["id"], name=p["name"], specialty=p["specialty"])
        for p in fx["providers"]
    ]
    prov_cfg = {p["id"]: p for p in fx["providers"]}

    # --- generate slots
    slots: dict[str, Slot] = {}
    for offset in range(fx["horizon_days"]):
        d = today + timedelta(days=offset)
        for p in fx["providers"]:
            if d.weekday() not in p["weekdays"] or _on_leave(p["id"], d, ov.provider_leave):
                continue
            for h_start, h_end in p["hours"]:
                t, block_end = clock.at(d, h_start), clock.at(d, h_end)
                while t + step <= block_end:
                    if t > now:
                        sid = f"slot_{p['id'].removeprefix('prov_')}_{t:%Y%m%d_%H%M}"
                        slots[sid] = Slot(
                            id=sid, sandbox_id=sandbox_id, provider_id=p["id"], specialty=p["specialty"],
                            start=t, end=t + step,
                            status=SlotStatus.BOOKED if _prefilled(p["id"], t, prefill) else SlotStatus.OPEN,
                        )
                    t += step

    # --- fixture + scenario appointments
    appointments: list[Appointment] = []
    fixture_appts = [FixtureAppointment(**a) for a in fx["appointments"]] + ov.extra_appointments
    for fa in fixture_appts:
        cfg = prov_cfg[fa.provider_id]
        if fa.date:
            d = date.fromisoformat(fa.date)
        else:
            d = today + timedelta(days=fa.day_offset or 0)
            while d.weekday() not in cfg["weekdays"]:
                d += timedelta(days=1)
        hh, mm = (int(x) for x in fa.time.split(":"))
        start = clock.at(d, hh, mm)
        sid = f"slot_{fa.provider_id.removeprefix('prov_')}_{start:%Y%m%d_%H%M}"
        if sid not in slots:
            continue  # outside horizon or in the past for this clock
        slots[sid].status = SlotStatus.BOOKED
        appointments.append(Appointment(
            id=fa.id, sandbox_id=sandbox_id, patient_id=fa.patient_id, provider_id=fa.provider_id,
            slot_id=sid, specialty=cfg["specialty"], start=start, end=start + step, reason=fa.reason,
        ))

    # --- fully booked days
    for fill in ov.fill_days:
        fd = date.fromisoformat(fill.date)
        for s in slots.values():
            if clock.local(s.start).date() != fd:
                continue
            if fill.specialty and s.specialty != fill.specialty:
                continue
            if fill.provider_id and s.provider_id != fill.provider_id:
                continue
            s.status = SlotStatus.BOOKED

    await repo.bulk_insert("patients", patients)
    await repo.bulk_insert("providers", providers)
    await repo.bulk_insert("slots", list(slots.values()))
    await repo.bulk_insert("appointments", appointments)

    open_count = sum(1 for s in slots.values() if s.status == SlotStatus.OPEN)
    return {
        "sandbox_id": sandbox_id,
        "patients": len(patients),
        "providers": len(providers),
        "slots": len(slots),
        "open_slots": open_count,
        "appointments": len(appointments),
    }
