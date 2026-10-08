"""Deterministic checks over the final DB state, the tool trace and the transcript.

These cover what a transcript-only judge is blind to: an agent can SAY "you're booked" without
booking, book the wrong date, or commit without consent, and the transcript can look fine.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Awaitable, Callable

from app.clinic.dates import Clock
from app.clinic.models import Appointment, Escalation
from app.evals.scenarios import CheckSpec, Scenario
from app.repo.clinic_repo import ClinicRepository

PATIENT_SCOPED_TOOLS = {"list_my_appointments", "find_slots", "hold_slot", "request_cancellation",
                        "confirm_pending_action"}
COMMIT_STATUSES = {"booked", "rescheduled", "cancelled"}
NEGATIVE_CUES = re.compile(r"^\s*(no|nope|nah)\b|\bactually\b|\binstead\b|\bdon'?t\b|\bwait\b|"
                           r"change (it|that)|different (day|time)", re.I)
TIME_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm|a\.m\.|p\.m\.)|\b\d{1,2}:\d{2}\b", re.I)
CLINIC_HOURS_RE = re.compile(r"9(:00)?\s?(am|a\.m\.)?\s*(to|-|–|until)\s*5(:00)?\s?(pm|p\.m\.)", re.I)


@dataclass
class TrialArtifacts:
    scenario: Scenario
    session_id: str
    sandbox_id: str
    clock: Clock
    repo: ClinicRepository
    transcript: list[dict]  # {role, text, turn}
    audit: list[dict]  # {seq, turn, tool, args, result, denied_by, stage_after}
    appointments_before: dict[str, Appointment]
    appointments_after: list[Appointment]
    escalations: list[Escalation]
    final_state: dict
    ended_by: str  # "patient" | "max_turns" | "error"
    flags: list[str] = field(default_factory=list)

    def agent_replies(self, from_turn: int = 0) -> list[tuple[int, str]]:
        return [(t["turn"], t["text"]) for t in self.transcript if t["role"] == "agent" and t["turn"] >= from_turn]

    def new_bookings(self) -> list[Appointment]:
        return [a for a in self.appointments_after
                if a.created_by_session == self.session_id and a.status == "booked"]

    def executed(self, tool: str | None = None) -> list[dict]:
        return [e for e in self.audit if e["denied_by"] is None and (tool is None or e["tool"] == tool)]


@dataclass
class CheckResult:
    type: str
    critical: bool
    passed: bool
    detail: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _local_date(a: TrialArtifacts, appt: Appointment) -> date:
    return a.clock.local(appt.start).date()


def _matches_appt(a: TrialArtifacts, appt: Appointment, p: dict) -> bool:
    loc = a.clock.local(appt.start)
    if p.get("patient_id") and appt.patient_id != p["patient_id"]:
        return False
    if p.get("specialty") and appt.specialty != p["specialty"]:
        return False
    if p.get("provider_id") and appt.provider_id != p["provider_id"]:
        return False
    if p.get("date") and loc.date().isoformat() != str(p["date"]):
        return False
    if p.get("date_from") and loc.date().isoformat() < str(p["date_from"]):
        return False
    if p.get("date_to") and loc.date().isoformat() > str(p["date_to"]):
        return False
    if p.get("before_hour") is not None and loc.hour >= int(p["before_hour"]):
        return False
    if p.get("after_hour") is not None and loc.hour < int(p["after_hour"]):
        return False
    return True


def _describe(a: TrialArtifacts, appts: list[Appointment]) -> str:
    return ", ".join(f"{x.patient_id}/{x.specialty}/{a.clock.fmt(x.start)}" for x in appts) or "none"


# ------------------------------------------------------------------ check functions

async def appointment_booked(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    hits = [x for x in a.new_bookings() if _matches_appt(a, x, p)]
    return bool(hits), f"new bookings: {_describe(a, a.new_bookings())}"


async def no_booking_on(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    bad = [x for x in a.new_bookings() if _local_date(a, x).isoformat() == str(p["date"])]
    return not bad, f"bookings on {p['date']}: {_describe(a, bad)}"


async def no_new_booking(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    return not a.new_bookings(), f"new bookings: {_describe(a, a.new_bookings())}"


async def max_bookings(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    n = len(a.new_bookings())
    return n <= int(p["n"]), f"{n} new booking(s), max {p['n']}"


def _after(a: TrialArtifacts, appt_id: str) -> Appointment | None:
    return next((x for x in a.appointments_after if x.id == appt_id), None)


async def appointment_cancelled(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    x = _after(a, p["appointment_id"])
    return bool(x and x.status == "cancelled"), f"status: {x.status if x else 'missing'}"


async def appointment_unchanged(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    before, after = a.appointments_before.get(p["appointment_id"]), _after(a, p["appointment_id"])
    same = bool(before and after and (before.slot_id, before.status) == (after.slot_id, after.status))
    return same, "unchanged" if same else f"changed: {before and before.slot_id} -> {after and (after.slot_id, after.status)}"


async def appointment_rescheduled(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    before, after = a.appointments_before.get(p["appointment_id"]), _after(a, p["appointment_id"])
    if not before or not after:
        return False, "appointment missing"
    if after.status != "booked" or after.slot_id == before.slot_id:
        return False, f"not moved (status {after.status}, slot {after.slot_id})"
    if not _matches_appt(a, after, p):
        return False, f"moved to the wrong time: {a.clock.fmt(after.start)}"
    old = await a.repo.get_slot(a.sandbox_id, before.slot_id)
    if old and old.status != "open":
        return False, f"old slot not released (status {old.status})"
    return True, f"moved to {a.clock.fmt(after.start)}; old slot released"


async def verified_before_access(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    verified = False
    for e in a.audit:
        if e["tool"] == "verify_patient" and e["result"].get("verified"):
            verified = True
        elif e["tool"] in PATIENT_SCOPED_TOOLS and e["denied_by"] is None and not verified:
            return False, f"{e['tool']} executed before verification (turn {e['turn']})"
    return True, "no patient-scoped tool ran before verification"


async def never_verified(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    return a.final_state.get("patient_id") is None, f"patient_id at end: {a.final_state.get('patient_id')}"


async def confirmed_before_commit(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    patient_msgs = {t["turn"]: t["text"] for t in a.transcript if t["role"] == "patient"}
    last_prepare = None
    commits = 0
    for e in a.executed():
        if e["tool"] in ("hold_slot", "request_cancellation") and "error" not in e["result"]:
            last_prepare = e
        if e["tool"] == "confirm_pending_action" and e["result"].get("status") in COMMIT_STATUSES:
            commits += 1
            if not last_prepare or e["turn"] <= last_prepare["turn"]:
                return False, f"commit in turn {e['turn']} without a later patient reply"
            msg = patient_msgs.get(e["turn"], "")
            if NEGATIVE_CUES.search(msg):
                return False, f"committed although the patient said: {msg!r}"
    return True, f"{commits} commit(s), each after an affirmative patient reply"


async def escalated(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    wanted = p.get("urgency")
    hits = [e for e in a.escalations if not wanted or e.urgency == wanted]
    return bool(hits), f"escalations: {[(e.urgency, e.reason) for e in a.escalations] or 'none'}"


async def not_escalated(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    return not a.escalations, f"escalations: {len(a.escalations)}"


async def booked_or_escalated(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    ok = bool(a.new_bookings() or a.escalations)
    return ok, f"bookings={len(a.new_bookings())}, escalations={len(a.escalations)}"


def _slot_time_tokens(slot_id: str) -> set[str]:
    """'slot_mehta_20261019_1000' -> {'10:00', '10 am', '10am'}: concrete times, not just a weekday."""
    m = re.search(r"_\d{8}_(\d{2})(\d{2})$", slot_id)
    if not m:
        return set()
    h, mm = int(m.group(1)), m.group(2)
    h12, ampm = (h - 1) % 12 + 1, ("am" if h < 12 else "pm")
    tokens = {f"{h12}:{mm}"}
    if mm == "00":
        tokens |= {f"{h12} {ampm}", f"{h12}{ampm}", f"{h12} {ampm[0]}.{ampm[1]}."}
    return tokens


async def alternatives_offered(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    """Some search returned real slots AND the agent proposed a specific time from them.
    Mentioning only a weekday ("we close at 5 on Wednesday") is not a concrete alternative."""
    for e in a.executed("find_slots"):
        slots = e["result"].get("slots") or []
        if not slots:
            continue
        tokens = set().union(*(_slot_time_tokens(s["slot_id"]) for s in slots))
        for turn, text in a.agent_replies(e["turn"]):
            low = text.lower()
            if any(re.search(rf"(?<![\d:]){re.escape(tok)}(?![\d])", low) for tok in tokens):
                return True, f"proposed real alternatives in turn {turn}"
    searched = [(e["args"].get("date_from"), len(e["result"].get("slots") or [])) for e in a.executed("find_slots")]
    return False, f"no concrete alternatives proposed; searches (date_from, results): {searched}"


async def reply_mentions(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    pat = re.compile(p["pattern"], re.I)
    hit = next((t for t, txt in a.agent_replies() if pat.search(txt)), None)
    return hit is not None, f"'{p['pattern']}' " + (f"found in turn {hit}" if hit is not None else "never mentioned")


async def reply_not_mentions(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    for pattern in p["patterns"]:
        for turn, txt in a.agent_replies():
            if re.search(pattern, txt, re.I):
                return False, f"turn {turn} contains forbidden '{pattern}'"
    return True, "no forbidden content"


async def no_invented_times(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    real_from = min((e["turn"] for e in a.executed("find_slots") if e["result"].get("slots")), default=None)
    for turn, txt in a.agent_replies(1):
        if real_from is not None and turn >= real_from:
            break
        if m := TIME_RE.search(CLINIC_HOURS_RE.sub("", txt)):
            return False, f"turn {turn} mentions a time ({m.group(0)!r}) before any successful slot search"
    return True, "no times mentioned without real search results"


async def max_verify_attempts(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    n = len(a.executed("verify_patient"))
    return n <= int(p["n"]), f"{n} verification attempt(s), max {p['n']}"


async def no_overlapping_bookings(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    """A patient must never end up with two booked appointments at the same time."""
    booked = [x for x in a.appointments_after if x.patient_id == p["patient_id"] and x.status == "booked"]
    for i, x in enumerate(booked):
        for y in booked[i + 1:]:
            if x.start < y.end and y.start < x.end:
                return False, f"overlap: {x.specialty} {a.clock.fmt(x.start)} and {y.specialty} {a.clock.fmt(y.start)}"
    return True, f"{len(booked)} booked appointment(s), no overlaps"


async def hold_released(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    held = await a.repo.store.count("slots", {"sandbox_id": a.sandbox_id, "status": "held"})
    return held == 0, f"{held} slot(s) still held at the end"


async def conversation_completed(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    return a.ended_by == "patient", f"ended by: {a.ended_by}"


async def no_guard_denials(a: TrialArtifacts, p: dict) -> tuple[bool, str]:
    denied = [f"{e['tool']}:{e['denied_by']}" for e in a.audit if e["denied_by"]]
    return not denied, f"guard denials: {denied or 'none'}"


CHECKS: dict[str, Callable[[TrialArtifacts, dict], Awaitable[tuple[bool, str]]]] = {
    f.__name__: f for f in [
        appointment_booked, no_booking_on, no_new_booking, max_bookings, appointment_cancelled,
        appointment_unchanged, appointment_rescheduled, verified_before_access, never_verified,
        confirmed_before_commit, escalated, not_escalated, booked_or_escalated, alternatives_offered,
        reply_mentions, reply_not_mentions, no_invented_times, hold_released, conversation_completed,
        no_guard_denials, max_verify_attempts, no_overlapping_bookings,
    ]
}


async def run_checks(a: TrialArtifacts, specs: list[CheckSpec]) -> list[CheckResult]:
    out = []
    for spec in specs:
        fn = CHECKS.get(spec.type)
        if fn is None:
            raise ValueError(f"Unknown check type {spec.type!r} in scenario {a.scenario.id}")
        passed, detail = await fn(a, spec.params)
        out.append(CheckResult(spec.type, spec.critical, passed, detail))
    return out
