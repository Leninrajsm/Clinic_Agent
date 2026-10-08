"""Applies analyzer edits to a policy markdown file, refusing anything unsafe or overfitted.

Allowed: add a rule to a section, or reword an existing rule. Never allowed: deleting rules,
weakening verification/confirmation/safety, or encoding test-specific facts (patient names,
dates, scenario ids) that would make the score move without real improvement.
"""

import re
import textwrap

from app.db.seed import load_fixture
from app.improve.patch import PolicyEdit

MAX_EDITS = 6
MAX_RULE_CHARS = 500
MAX_POLICY_CHARS = 9000

WEAKENING = [
    re.compile(r"\b(skip|bypass|ignore|omit|no need (to|for)|not necessary to|without)\b(\s+\w+){0,4}\s+"
               r"(verif\w*|identity|date of birth|confirm\w*|consent|safety|emergenc\w*|911)", re.I),
    re.compile(r"\b(may|can|should|okay to|ok to|allowed to)\b(\s+\w+){0,3}\s+(give|offer|provide|share)\b"
               r"(\s+\w+){0,3}\s+(medical|medication|dosage|diagnos\w*|treatment)\b", re.I),
    re.compile(r"\b(share|disclose|reveal)\b(\s+\w+){0,4}\s+(another|other|family|spouse|wife|husband)", re.I),
    re.compile(r"\bconfirm_pending_action\b[^.]{0,60}\b(same turn|immediately|without asking)", re.I),
]
ISO_DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
SPECIFIC_DATE = re.compile(
    r"\b(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|"
    r"nov(ember)?|dec(ember)?)\.? \d{1,2}(st|nd|rd|th)?\b", re.I)
# "Never book without confirmation" / "Do not skip verification" strengthen rules, so a negation
# shortly before a weakening phrase makes it acceptable.
NEGATED = re.compile(r"\b(never|not|don'?t|do not|must not|no|cannot|can'?t)\b[^.;:]{0,30}$", re.I)
PREFIX_TERMS = ("slot_", "pt_", "appt_", "prov_", "scenario")


def _patient_names() -> set[str]:
    fx = load_fixture()
    return {p["first_name"].lower() for p in fx["patients"]} | {p["last_name"].lower() for p in fx["patients"]}


def _weakens(text: str) -> bool:
    for pat in WEAKENING:
        for m in pat.finditer(text):
            if not NEGATED.search(text[: m.start()]):
                return True
    return False


def validate_edit(edit: PolicyEdit, scenario_ids: set[str]) -> str | None:
    text = edit.new_text.strip()
    if not (10 <= len(text) <= MAX_RULE_CHARS):
        return f"rule length {len(text)} outside 10..{MAX_RULE_CHARS}"
    if _weakens(text):
        return f"rejected as weakening a safety rule: {text[:80]!r}"
    low = text.lower()
    if ISO_DATE.search(text) or SPECIFIC_DATE.search(text):
        return "rule mentions a specific date (overfitting to a test)"
    words = _patient_names() | {s.lower() for s in scenario_ids}
    hit = next((w for w in words if re.search(rf"\b{re.escape(w)}\b", low)), None) or \
        next((t for t in PREFIX_TERMS if t in low), None)
    if hit:
        return f"rule mentions test-specific term {hit!r} (overfitting)"
    if edit.operation == "replace_rule" and not (edit.old_text or "").strip():
        return "replace_rule needs old_text"
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lstrip("-").strip()).lower()


def _bullet(text: str) -> list[str]:
    return textwrap.wrap(text.strip(), width=95, initial_indent="- ", subsequent_indent="  ")


def _section_bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    start = next((i for i, l in enumerate(lines)
                  if l.startswith("## ") and _norm(l[3:]) == _norm(section)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end


def _bullets(lines: list[str], start: int, end: int) -> list[tuple[int, int, str]]:
    """(first_line, last_line_exclusive, joined_text) for each bullet in a section."""
    out, i = [], start + 1
    while i < end:
        if lines[i].startswith("- "):
            j = i + 1
            while j < end and lines[j].startswith("  ") and lines[j].strip():
                j += 1
            out.append((i, j, " ".join(l.strip() for l in lines[i:j])))
            i = j
        else:
            i += 1
    return out


def apply_edit(policy: str, edit: PolicyEdit) -> str:
    lines = policy.rstrip("\n").split("\n")
    bounds = _section_bounds(lines, edit.section)
    if edit.operation == "add_rule":
        if bounds is None:
            return "\n".join(lines + ["", f"## {edit.section.strip()}"] + _bullet(edit.new_text)) + "\n"
        start, end = bounds
        insert_at = end
        while insert_at > start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        return "\n".join(lines[:insert_at] + _bullet(edit.new_text) + lines[insert_at:]) + "\n"

    if bounds is None:
        raise ValueError(f"section {edit.section!r} not found for replace_rule")
    target = _norm(edit.old_text or "")
    for first, last, text in _bullets(lines, *bounds):
        if _norm(text) == target or (len(target) > 20 and target in _norm(text)):
            return "\n".join(lines[:first] + _bullet(edit.new_text) + lines[last:]) + "\n"
    raise ValueError(f"rule to replace not found in section {edit.section!r}: {edit.old_text!r}")


def apply_edits(policy: str, edits: list[PolicyEdit], scenario_ids: set[str]) -> tuple[str, list[str], list[str]]:
    """Returns (new_policy, applied_descriptions, rejected_reasons)."""
    applied, rejected = [], []
    if len(edits) > MAX_EDITS:
        rejected.append(f"{len(edits) - MAX_EDITS} edit(s) dropped: at most {MAX_EDITS} per attempt")
        edits = edits[:MAX_EDITS]
    new = policy
    for e in edits:
        problem = validate_edit(e, scenario_ids)
        if problem:
            rejected.append(f"[{e.section}] {problem}")
            continue
        try:
            new = apply_edit(new, e)
            applied.append(f"{e.operation} in '{e.section}': {e.new_text.strip()}")
        except ValueError as exc:
            rejected.append(str(exc))
    if len(new) > MAX_POLICY_CHARS:
        return policy, [], rejected + [f"policy would exceed {MAX_POLICY_CHARS} characters"]
    return new, applied, rejected


def bump_title(policy: str, version: str) -> str:
    lines = policy.split("\n")
    if lines and lines[0].startswith("# "):
        lines[0] = f"# Scheduling policy {version}"
    return "\n".join(lines)
