"""Provider-neutral LLM types. The agent, simulator, judge and analyzer only see these,
which also lets tests drive the agent with a scripted fake model."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON schema (type: object)


@dataclass
class ToolCall:
    name: str
    args: dict
    id: str | None = None


@dataclass
class ToolResult:
    name: str
    result: dict
    id: str | None = None


@dataclass
class Message:
    role: Literal["user", "model", "tool"]
    text: str = ""
    tool_results: list[ToolResult] = field(default_factory=list)
    raw: Any = None  # provider-native content (keeps function calls + thought signatures intact)


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    raw: Any = None
    parsed: BaseModel | None = None
    finish_reason: str | None = None


class LLMError(RuntimeError):
    pass


class LLMBudgetExceeded(LLMError):
    pass


class LLMClient(Protocol):
    async def generate(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        json_schema: type[BaseModel] | None = None,
        purpose: str = "agent",
    ) -> LLMResponse: ...
