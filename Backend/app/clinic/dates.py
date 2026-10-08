"""Clock and relative-date resolution.

LLMs are unreliable at calendar arithmetic ("next Friday" from a Monday), so date resolution
is deterministic code exposed to the agent as a tool. Evals freeze the clock so every run
resolves dates identically.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_MO = "|".join(sorted(MONTHS, key=len, reverse=True))


class Clock:
    """Clinic-local clock. `frozen` pins "now" for reproducible evals and demos."""

    def __init__(self, timezone: str, frozen: datetime | None = None):
        self.tz = ZoneInfo(timezone)
        self._frozen = frozen.astimezone(self.tz) if frozen and frozen.tzinfo else (
            frozen.replace(tzinfo=self.tz) if frozen else None
        )

    @classmethod
    def from_iso(cls, timezone: str, frozen_iso: str | None) -> "Clock":
        return cls(timezone, datetime.fromisoformat(frozen_iso) if frozen_iso else None)

    def now(self) -> datetime:
        return self._frozen or datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()

    def at(self, d: date, hour: int, minute: int = 0) -> datetime:
        return datetime(d.year, d.month, d.day, hour, minute, tzinfo=self.tz)

    def local(self, dt: datetime) -> datetime:
        return dt.astimezone(self.tz)

    def fmt(self, dt: datetime) -> str:
        """Human-friendly clinic-local format, e.g. 'Fri Oct 16, 9:00 AM'."""
        loc = self.local(dt)
        return loc.strftime("%a %b %d, %I:%M %p").replace(" 0", " ")


@dataclass
class DateResolution:
    start: date | None = None
    end: date | None = None
    interpretation: str = ""
    ambiguous: bool = False
    alternatives: list[str] = field(default_factory=list)
    time_of_day: str | None = None  # "morning" | "afternoon" | "evening"
    error: str | None = None

    def to_dict(self) -> dict:
        d = {
            "interpretation": self.interpretation,
            "ambiguous": self.ambiguous,
        }
        if self.error:
            return {"error": self.error}
        d["date_from"] = self.start.isoformat()
        d["date_to"] = self.end.isoformat()
        if self.alternatives:
            d["alternatives"] = self.alternatives
        if self.time_of_day:
            d["time_of_day"] = self.time_of_day
        return d


def _label(d: date) -> str:
    return d.strftime("%A %b %d, %Y").replace(" 0", " ")


def _single(d: date, note: str = "") -> DateResolution:
    return DateResolution(start=d, end=d, interpretation=f"{_label(d)}{note}")


def resolve_date(text: str, today: date) -> DateResolution:
    raw = text.strip().lower()
    t = re.sub(r"[,.!?]", " ", raw)
    t = re.sub(r"\s+", " ", t).strip()

    tod = None
    for word in ("morning", "afternoon", "evening"):
        if word in t:
            tod = word
            t = t.replace(word, "").strip()
    res = _resolve(t, today)
    if res.error is None:
        res.time_of_day = tod
        if res.start and res.start < today:
            return DateResolution(error=f"'{text}' is in the past (today is {_label(today)}).")
    return res


def _resolve(t: str, today: date) -> DateResolution:
    if t in ("", "asap", "soon", "sometime soon", "whenever", "any time", "anytime", "earliest"):
        return DateResolution(
            error="No specific date given. Ask the patient which day or week they prefer."
        )
    if t == "today":
        return _single(today)
    if t == "tomorrow":
        return _single(today + timedelta(days=1))
    if t in ("day after tomorrow", "the day after tomorrow"):
        return _single(today + timedelta(days=2))

    # this week / next week
    monday = today - timedelta(days=today.weekday())
    if t in ("this week", "later this week", "rest of this week"):
        end = monday + timedelta(days=6)
        return DateResolution(start=today, end=end, interpretation=f"{_label(today)} to {_label(end)}")
    if t in ("next week", "sometime next week"):
        start = monday + timedelta(days=7)
        end = start + timedelta(days=6)
        return DateResolution(start=start, end=end, interpretation=f"week of {_label(start)}")
    if t in ("next two weeks", "next 2 weeks", "in the next two weeks", "in the next 2 weeks"):
        end = today + timedelta(days=14)
        return DateResolution(start=today, end=end, interpretation=f"{_label(today)} to {_label(end)}")

    m = re.fullmatch(r"in (\d{1,2}) (day|days|week|weeks)", t)
    if m:
        n = int(m.group(1)) * (7 if m.group(2).startswith("week") else 1)
        return _single(today + timedelta(days=n))
    m = re.fullmatch(r"(?:in )?the next (\d{1,2}) days|next (\d{1,2}) days", t)
    if m:
        n = int(m.group(1) or m.group(2))
        end = today + timedelta(days=n)
        return DateResolution(start=today, end=end, interpretation=f"{_label(today)} to {_label(end)}")

    # "<weekday> next week" / "next week <weekday>"
    m = re.fullmatch(rf"(?:on )?({_WD}) (?:of )?next week|next week (?:on )?({_WD})", t)
    if m:
        wd = WEEKDAYS[m.group(1) or m.group(2)]
        return _single(monday + timedelta(days=7 + wd))

    # "[this|coming|next|on] <weekday>"
    m = re.fullmatch(rf"(this|coming|this coming|next|on)? ?({_WD})", t)
    if m:
        mod, wd = m.group(1), WEEKDAYS[m.group(2)]
        delta = (wd - today.weekday()) % 7
        upcoming = today + timedelta(days=delta)
        if mod == "next":
            if delta == 0:
                return _single(today + timedelta(days=7))
            if wd > today.weekday():
                # Same calendar week: people mean either this one or the following one.
                alt = upcoming + timedelta(days=7)
                return DateResolution(
                    start=upcoming, end=upcoming, ambiguous=True,
                    interpretation=f"{_label(upcoming)} (could also mean {_label(alt)})",
                    alternatives=[alt.isoformat()],
                )
            return _single(upcoming)
        if delta == 0:
            alt = today + timedelta(days=7)
            return DateResolution(
                start=today, end=today, ambiguous=True,
                interpretation=f"today, {_label(today)} (could also mean {_label(alt)})",
                alternatives=[alt.isoformat()],
            )
        return _single(upcoming)

    explicit = _explicit_date(t, today)
    if explicit:
        return _single(explicit)

    return DateResolution(
        error=f"Could not interpret '{t}'. Ask the patient for a specific day (e.g. 'Friday' or 'Oct 16')."
    )


def _explicit_date(t: str, today: date) -> date | None:
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    t = re.sub(r"^(on|the) ", "", t)
    t = re.sub(rf"^(?:{_WD}) ", "", t)  # "friday oct 16" -> "oct 16"
    year = None
    try:
        return date.fromisoformat(t)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
    else:
        m = re.fullmatch(rf"({_MO}) (\d{{1,2}})(?: (\d{{4}}))?", t) or None
        if m:
            month, day = MONTHS[m.group(1)], int(m.group(2))
            year = int(m.group(3)) if m.group(3) else None
        else:
            m = re.fullmatch(rf"(\d{{1,2}}) (?:of )?({_MO})(?: (\d{{4}}))?", t)
            if not m:
                return None
            day, month = int(m.group(1)), MONTHS[m.group(2)]
            year = int(m.group(3)) if m.group(3) else None
    if year is not None and year < 100:
        year += 2000
    try:
        d = date(year or today.year, month, day)
    except ValueError:
        return None
    if year is None and d < today:
        d = date(today.year + 1, month, day)
    return d
