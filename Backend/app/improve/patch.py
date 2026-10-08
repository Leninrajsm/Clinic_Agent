"""Structured improvement proposals produced by the analyzer.

No field defaults on purpose: these models are sent to Gemini as a response schema, and the
schema converter rejects default values. Nullable fields are explicit instead."""

from typing import Literal

from pydantic import BaseModel


class PolicyEdit(BaseModel):
    operation: Literal["add_rule", "replace_rule"]
    section: str  # policy heading, e.g. "Booking" (a new section is created if it doesn't exist)
    old_text: str | None  # replace_rule: the existing rule text to replace; null for add_rule
    new_text: str


class Proposal(BaseModel):
    failure_cluster: str  # short name for the failure pattern
    root_cause: str
    fix_type: Literal["policy_edit", "needs_code_change"]
    edits: list[PolicyEdit]
    target_scenarios: list[str]
    expected_effect: str
    code_change_ticket: str | None  # for needs_code_change: what an engineer should change


class AnalyzerOutput(BaseModel):
    proposals: list[Proposal]
