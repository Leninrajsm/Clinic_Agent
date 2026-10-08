from datetime import datetime

import pytest

from app.agent.orchestrator import ClinicAgent
from app.clinic.dates import Clock
from app.config import Settings
from app.db.seed import SeedOverrides, seed_sandbox
from app.llm.base import LLMResponse, ToolCall
from app.policy.store import PolicyStore
from app.repo.clinic_repo import ClinicRepository
from app.repo.store import MemoryStore

SANDBOX = "test"
FROZEN = datetime.fromisoformat("2026-10-12T09:00:00")  # a Monday


class ScriptedLLM:
    """Fake model. Each script step is either reply text, or a list of (tool_name, args) calls."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []

    async def generate(self, *, model, system, messages, tools=None, temperature=None, json_schema=None,
                       purpose="agent"):
        self.calls.append({"system": system, "tools": [t.name for t in tools or []]})
        if not self.script:
            raise AssertionError("ScriptedLLM ran out of steps")
        step = self.script.pop(0)
        if isinstance(step, str):
            return LLMResponse(text=step, tool_calls=[])
        return LLMResponse(text="", tool_calls=[ToolCall(name=n, args=a, id=None) for n, a in step])


class RoutingLLM:
    """Fake model for harness/loop tests: separate scripts per purpose; the judge gives 5/5 to every
    criterion; the analyzer returns a canned AnalyzerOutput."""

    def __init__(self, agent=None, simulator=None, analyzer=None, judge_score: int = 5):
        self.agent = ScriptedLLM(agent or [])
        self.simulator = list(simulator or [])
        self.analyzer = analyzer
        self.judge_score = judge_score
        self.purposes: list[str] = []

    async def generate(self, *, model, system, messages, tools=None, temperature=None, json_schema=None,
                       purpose="agent"):
        from app.evals.judge import RUBRIC, JudgeOutput, RubricScore

        self.purposes.append(purpose)
        if purpose == "agent":
            return await self.agent.generate(model=model, system=system, messages=messages, tools=tools)
        if purpose == "simulator":
            return LLMResponse(text=self.simulator.pop(0), tool_calls=[])
        if purpose == "judge":
            out = JudgeOutput(scores=[RubricScore(id=k, score=self.judge_score, reason="ok") for k in RUBRIC],
                              summary="fake")
            return LLMResponse(text="", tool_calls=[], parsed=out)
        if purpose == "analyzer":
            return LLMResponse(text="", tool_calls=[], parsed=self.analyzer)
        raise AssertionError(purpose)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, gemini_api_key="test")


@pytest.fixture
def clock() -> Clock:
    return Clock("America/New_York", FROZEN)


@pytest.fixture
async def repo(clock) -> ClinicRepository:
    r = ClinicRepository(MemoryStore())
    await seed_sandbox(r, SANDBOX, clock, SeedOverrides(prefill_percent=0))
    return r


@pytest.fixture
def make_agent(repo, clock, settings):
    def _make(script: list) -> tuple[ClinicAgent, ScriptedLLM]:
        llm = ScriptedLLM(script)
        return ClinicAgent(repo, llm, clock, settings, PolicyStore(), model="fake"), llm

    return _make
