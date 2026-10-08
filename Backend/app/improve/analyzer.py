"""Turns failed eval trials into structured, general policy improvements."""

import json

from app.agent.tools import tool_specs
from app.evals.runner import RunResult, ScenarioResult
from app.evals.scenarios import Scenario
from app.improve.patch import AnalyzerOutput
from app.llm.base import LLMClient, LLMError, Message

ANALYZER_SYSTEM = """You improve the written policy of an AI scheduling assistant for a medical clinic.
The assistant follows: (1) a locked safety core, (2) the editable POLICY below, and (3) tools whose
behaviour you cannot change. Code-level guards already enforce identity verification, consent
before commit, privacy and emergency handling, so never try to re-implement or relax those.

You get evidence from failed test conversations: which deterministic checks failed, what a
transcript judge said, the transcript, and the tool trace. Your job:
1. Group the failures into patterns and find the root cause of each in the assistant's behaviour.
2. Propose the SMALLEST policy changes that fix the pattern in general, for any patient, date,
   doctor or specialty. Never mention patient names, specific dates, slot ids or test names:
   rules must describe the general situation (e.g. "when a search returns no slots ...").
3. Prefer adding one clear rule to the relevant existing section, or rewording an existing rule
   (replace_rule with the exact old text). Never delete or weaken rules.
4. Make sure your change would not break the currently passing scenarios listed.
5. If the root cause is not something a policy can fix (a missing tool capability, a tool bug,
   a test that is wrong), use fix_type "needs_code_change", leave edits empty, and write a
   precise engineering ticket in code_change_ticket.
6. target_scenarios: the failing scenario ids this proposal should fix.
Return JSON only."""


def _trim(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 3] + "..."


def _trial_evidence(r: ScenarioResult, max_trials: int = 2) -> str:
    out = []
    failing = [t for t in r.trials if t.status == "ok" and not t.passed][:max_trials]
    for t in failing:
        failed = [f"{c['type']}: {c['detail']}" for c in t.checks if not c["passed"]]
        low = [f"{s['id']}={s['score']}/5: {s['reason']}" for s in t.judge.get("scores", []) if not s["passed"]]
        convo = "\n".join(f"    {'PATIENT' if m['role'] == 'patient' else 'ASSISTANT'}: {_trim(m['text'], 300)}"
                          for m in t.transcript)
        trace = "\n".join(
            f"    turn {e['turn']}: {e['tool']}({_trim(json.dumps(e['args'], default=str), 120)}) -> "
            f"{_trim(json.dumps(e['result'], default=str), 160)}"
            + (f" [DENIED by guard: {e['denied_by']}]" if e.get("denied_by") else "")
            for e in t.tool_trace
        )
        out.append(f"  Trial {t.trial}:\n  Failed checks: {failed or 'none'}\n  Judge: {low or 'ok'}\n"
                   f"  Transcript:\n{convo}\n  Tool trace:\n{trace or '    (no tool calls)'}")
    return "\n".join(out)


def build_analyzer_prompt(policy_text: str, run: RunResult, scenarios: dict[str, Scenario],
                          failing_ids: list[str], feedback: list[str] | None) -> str:
    tools = "\n".join(f"- {s.name}: {s.description}" for s in tool_specs().values())
    by_id = run.by_id()
    failing = "\n\n".join(
        f"### {sid} ({scenarios[sid].category})\nGoal: {scenarios[sid].description}\n"
        f"Pass rate: {by_id[sid].pass_rate}\n{_trial_evidence(by_id[sid])}"
        for sid in failing_ids
    )
    passing = "\n".join(f"- {r.scenario_id}: {r.description}" for r in run.results if r.passed)
    parts = [
        f"## Current POLICY ({run.policy_version})\n{policy_text}",
        f"## Tools available to the assistant\n{tools}",
        f"## Failing scenarios\n{failing}",
        f"## Currently passing scenarios (must keep passing)\n{passing or '(none)'}",
    ]
    if feedback:
        parts.append("## Your previous attempt was rejected\n" + "\n".join(f"- {f}" for f in feedback)
                     + "\nPropose a different or narrower change.")
    return "\n\n".join(parts)


async def analyze(llm: LLMClient, model: str, policy_text: str, run: RunResult, scenarios: dict[str, Scenario],
                  failing_ids: list[str], feedback: list[str] | None = None) -> AnalyzerOutput:
    prompt = build_analyzer_prompt(policy_text, run, scenarios, failing_ids, feedback)
    resp = await llm.generate(model=model, system=ANALYZER_SYSTEM, messages=[Message("user", prompt)],
                              json_schema=AnalyzerOutput, purpose="analyzer")
    if resp.parsed is None:
        raise LLMError("analyzer returned no structured output")
    return resp.parsed
