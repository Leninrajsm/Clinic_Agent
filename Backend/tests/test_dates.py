from datetime import date

import pytest

from app.clinic.dates import resolve_date

MONDAY = date(2026, 10, 12)


@pytest.mark.parametrize("text,expected", [
    ("today", "2026-10-12"),
    ("tomorrow", "2026-10-13"),
    ("Friday", "2026-10-16"),
    ("this friday", "2026-10-16"),
    ("friday next week", "2026-10-23"),
    ("next monday", "2026-10-19"),
    ("Oct 16", "2026-10-16"),
    ("16th October", "2026-10-16"),
    ("10/16", "2026-10-16"),
    ("2026-10-20", "2026-10-20"),
    ("in 3 days", "2026-10-15"),
])
def test_single_dates(text, expected):
    res = resolve_date(text, MONDAY)
    assert res.error is None
    assert res.start.isoformat() == expected


def test_next_friday_from_monday_is_ambiguous():
    res = resolve_date("next Friday", MONDAY)
    assert res.ambiguous
    assert res.start.isoformat() == "2026-10-16"
    assert res.alternatives == ["2026-10-23"]


def test_time_of_day_is_extracted():
    res = resolve_date("Friday morning", MONDAY)
    assert res.start.isoformat() == "2026-10-16" and res.time_of_day == "morning"


def test_next_week_is_a_range():
    res = resolve_date("next week", MONDAY)
    assert (res.start.isoformat(), res.end.isoformat()) == ("2026-10-19", "2026-10-25")


@pytest.mark.parametrize("text", ["sometime soon", "whenever", "blue moon"])
def test_vague_or_unknown_returns_error(text):
    assert resolve_date(text, MONDAY).error


def test_month_day_in_past_rolls_to_next_year():
    assert resolve_date("Jan 5", MONDAY).start.isoformat() == "2027-01-05"


def test_explicit_past_date_is_rejected():
    assert "past" in resolve_date("2026-10-01", MONDAY).error
