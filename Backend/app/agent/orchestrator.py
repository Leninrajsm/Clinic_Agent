"""One patient turn:

  [1] safety pre-check (code, before any LLM call)
  [2] model <-> tool loop; every tool call passes the guard layer; prompt rebuilt as state changes
  [3] grounding check: no "you're booked" unless a commit actually happened
  [4] persist transcript, state and audit log
"""

import re

from pydantic import BaseModel

from app.agent.context import ToolContext
from app.agent.prompt_builder import build_system_prompt
from app.agent.safety import check_message
from app.agent.state import Session, Stage, TranscriptTurn
from app.agent.tools import execute_tool, system_escalate, tool_specs
from app.clinic.dates import Clock
from app.config import Settings
from app.db.seed import clinic_info
from app.llm.base import LLMClient, LLMError, Message, ToolResult
from app.policy.store import PolicyStore
from app.repo.clinic_repo import ClinicRepository

CONNECT_MESSAGE = "(The patient has opened the clinic chat.)"

CLAIM_PATTERNS = [
    r"\byou(?:'re| are) (?:all set|booked|scheduled|confirmed)\b",
    r"\bi(?:'ve| have) (?:now |just |successfully )?(?:booked|scheduled|cancel+ed|rescheduled|confirmed|moved)\b",
    r"\b(?:your|the) (?:appointment|booking|visit)(?: \w+){0,6}? (?:is|has been|was) (?:now )?"
    r"(?:booked|scheduled|confirmed|cancel+ed|rescheduled|moved)\b",
    r"\bsuccessfully (?:booked|scheduled|cancel+ed|rescheduled)\b",
]


class TurnResult(BaseModel):
    session_id: str
    reply: str
    stage: str
    state: dict
    tool_events: list[dict]
    flags: list[str]


class ClinicAgent:
    def __init__(
        self,
        repo: ClinicRepository,
        llm: LLMClient,
        clock: Clock,
        settings: Settings,
        policies: PolicyStore,
        model: str | None = None,
    ):
        self.repo, self.llm, self.clock, self.settings, self.policies = repo, llm, clock, settings, policies
        self.model = model or settings.model_agent
        self._specs = tool_specs()
        self._faults: dict[str, dict[str, int]] = {}

    def greeting(self) -> str:
        return (f"Hello, thanks for contacting {clinic_info()['name']}. I can help you book, reschedule or "
                "cancel an appointment. How can I help today?")

    async def start_session(
        self, sandbox_id: str, policy_version: str | None = None, faults: dict[str, int] | None = None
    ) -> Session:
        session = Session(
            sandbox_id=sandbox_id,
            policy_version=policy_version or self.policies.active_version(),
            created_at=self.clock.now(),
        )
        session.transcript.append(TranscriptTurn(role="agent", text=self.greeting(), turn=0))
        self._faults[session.id] = dict(faults or {})
        await self.repo.save_session(session.model_dump(mode="json"))
        return session

    async def load_session(self, session_id: str) -> Session:
        doc = await self.repo.get_session(session_id)
        if doc is None:
            raise KeyError(f"Unknown session {session_id!r}")
        return Session(**doc)

    # ------------------------------------------------------------------ turn

    async def respond(self, session_id: str, patient_text: str) -> TurnResult:
        session = await self.load_session(session_id)
        st = session.state
        st.turn += 1
        session.transcript.append(TranscriptTurn(role="patient", text=patient_text, turn=st.turn))
        ctx = ToolContext(self.repo, self.clock, self.settings, session,
                          faults=self._faults.setdefault(session.id, {}))
        events: list[dict] = []
        flags: list[str] = []

        hit = check_message(patient_text)
        if hit:
            await system_escalate(ctx, f"{hit.category} red flag: '{hit.matched}'", "emergency")
            await self._audit(ctx, "safety_precheck", {"matched": hit.matched}, {"category": hit.category}, None)
            flags.append(f"safety_{hit.category}")
            reply = hit.reply
        else:
            reply = await self._model_loop(ctx, session, events, flags)
            reply = await self._ground(ctx, reply, flags)

        session.transcript.append(TranscriptTurn(role="agent", text=reply, turn=st.turn))
        await self.repo.save_session(session.model_dump(mode="json"))
        return TurnResult(session_id=session.id, reply=reply, stage=st.stage.value,
                          state=st.model_dump(mode="json"), tool_events=events, flags=flags)

    async def _model_loop(self, ctx: ToolContext, session: Session, events: list[dict], flags: list[str]) -> str:
        st = ctx.state
        policy_text = self.policies.text(session.policy_version)
        safety_core = self.policies.safety_core()
        messages = [Message("user", CONNECT_MESSAGE)] + [
            Message("user" if t.role == "patient" else "model", t.text) for t in session.transcript
        ]
        limit = self.settings.max_tool_calls_per_turn
        used = 0
        while True:
            system = build_system_prompt(safety_core, policy_text, session.policy_version, st, self.clock,
                                         self.settings.max_verification_attempts)
            tools = [self._specs[n] for n in sorted(st.allowed_tools())]
            try:
                resp = await self.llm.generate(model=self.model, system=system, messages=messages,
                                               tools=tools, purpose="agent")
            except LLMError:
                flags.append("llm_error")
                return ("I'm sorry, I'm having technical difficulties right now. Please try again in a moment, "
                        f"or call the clinic at {clinic_info()['phone']}.")

            if not resp.tool_calls:
                if resp.text:
                    return resp.text
                flags.append("empty_response")
                return "Sorry, could you say that again?"

            if used + len(resp.tool_calls) > limit:
                flags.append("tool_call_limit")
                return ("I'm sorry, I'm having trouble completing that. Would you like me to have a staff member "
                        "follow up with you?")

            messages.append(Message("model", text=resp.text, raw=resp.raw))
            results = []
            for call in resp.tool_calls:
                used += 1
                result, denied = await execute_tool(call.name, call.args, ctx)
                if denied:
                    flags.append(f"guard:{denied}")
                event = await self._audit(ctx, call.name, call.args, result, denied)
                events.append(event)
                results.append(ToolResult(name=call.name, result=result, id=call.id))
            messages.append(Message("tool", tool_results=results))

    async def _ground(self, ctx: ToolContext, reply: str, flags: list[str]) -> str:
        """Block success claims that no tool result backs up."""
        st = ctx.state
        claims = any(re.search(p, reply.lower()) for p in CLAIM_PATTERNS)
        backed = bool(ctx.committed_this_turn) or (bool(st.completed) and st.pending is None)
        if not claims or backed or st.stage == Stage.ESCALATED:
            return reply
        flags.append("grounding_correction")
        await self._audit(ctx, "grounding_check", {"reply": reply}, {"corrected": True}, None)
        if st.pending:
            return (f"Sorry, I need to correct myself: that isn't final yet. To confirm: {st.pending.summary}. "
                    "Shall I go ahead?")
        return ("Sorry, I need to correct myself: I haven't made that change yet. "
                "Would you like me to go ahead with it?")

    async def _audit(self, ctx: ToolContext, tool: str, args: dict, result: dict, denied: str | None) -> dict:
        st = ctx.state
        st.audit_seq += 1
        entry = {
            "session_id": ctx.session.id, "sandbox_id": ctx.sandbox_id, "seq": st.audit_seq, "turn": st.turn,
            "tool": tool, "args": args, "result": result, "denied_by": denied,
            "stage_after": st.stage.value, "ts": self.clock.now(),
        }
        await self.repo.add_audit(entry)
        return {k: v for k, v in entry.items() if k not in ("session_id", "sandbox_id", "ts")}
