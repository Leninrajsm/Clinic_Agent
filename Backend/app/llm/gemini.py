"""Gemini implementation of LLMClient: throttling, retry with backoff, call budget, usage stats."""

import asyncio
import logging
import random
import re
import time
from collections import Counter

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from app.config import Settings
from app.llm.base import LLMBudgetExceeded, LLMError, LLMResponse, Message, ToolCall, ToolSpec

log = logging.getLogger(__name__)

RETRYABLE = {429, 500, 502, 503, 504}


class GeminiClient:
    def __init__(self, settings: Settings):
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set. Add it to Backend/.env (see .env.example).")
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._sem = asyncio.Semaphore(settings.llm_max_concurrency)
        self._min_interval = 60.0 / max(settings.llm_max_rpm, 1)
        self._last_call = 0.0
        self._pace_lock = asyncio.Lock()
        self._max_retries = settings.llm_max_retries
        self.budget = settings.llm_call_budget
        self.calls: Counter[str] = Counter()
        self.tokens: Counter[str] = Counter()

    # ------------------------------------------------------------------ conversion

    @staticmethod
    def _to_contents(messages: list[Message]) -> list[types.Content]:
        out: list[types.Content] = []
        for m in messages:
            if m.raw is not None:
                out.append(m.raw)
            elif m.role == "tool":
                out.append(types.Content(role="user", parts=[
                    types.Part(function_response=types.FunctionResponse(id=r.id, name=r.name, response=r.result))
                    for r in m.tool_results
                ]))
            else:
                out.append(types.Content(role=m.role, parts=[types.Part(text=m.text)]))
        return out

    @staticmethod
    def _to_tools(tools: list[ToolSpec]) -> list[types.Tool]:
        return [types.Tool(function_declarations=[
            types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
            for t in tools
        ])]

    # ------------------------------------------------------------------ pacing

    async def _pace(self) -> None:
        async with self._pace_lock:
            wait = self._last_call + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    @staticmethod
    def _retry_after(exc: Exception, attempt: int) -> float:
        m = re.search(r"retry(?:Delay)?['\"]?:?\s*['\"]?(?:in )?(\d+(?:\.\d+)?)s", str(exc), re.I)
        base = float(m.group(1)) if m else min(60.0, 2.0 ** attempt)
        return base + random.uniform(0, 1.5)

    # ------------------------------------------------------------------ generate

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
    ) -> LLMResponse:
        if sum(self.calls.values()) >= self.budget:
            raise LLMBudgetExceeded(f"LLM call budget of {self.budget} reached (LLM_CALL_BUDGET).")

        config = types.GenerateContentConfig(system_instruction=system)
        if temperature is not None:
            config.temperature = temperature
        if tools:
            config.tools = self._to_tools(tools)
            config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        if json_schema is not None:
            config.response_mime_type = "application/json"
            config.response_schema = json_schema

        contents = self._to_contents(messages)
        resp = None
        for attempt in range(self._max_retries + 1):
            async with self._sem:
                await self._pace()
                try:
                    resp = await self._client.aio.models.generate_content(
                        model=model, contents=contents, config=config
                    )
                    self.calls[purpose] += 1
                except genai_errors.APIError as exc:
                    self.calls[f"{purpose}_errors"] += 1
                    if exc.code not in RETRYABLE or attempt == self._max_retries:
                        raise LLMError(f"Gemini error ({model}): {exc}") from exc
                    code, delay = exc.code, self._retry_after(exc, attempt)
            if resp is not None:
                break
            log.warning("Gemini %s (%s), retrying in %.1fs", code, purpose, delay)
            await asyncio.sleep(delay)

        usage = getattr(resp, "usage_metadata", None)
        if usage:
            self.tokens[f"{purpose}_in"] += usage.prompt_token_count or 0
            self.tokens[f"{purpose}_out"] += usage.candidates_token_count or 0
            self.tokens[f"{purpose}_thinking"] += getattr(usage, "thoughts_token_count", 0) or 0  # billed as output

        if not resp.candidates or resp.candidates[0].content is None:
            reason = resp.candidates[0].finish_reason if resp.candidates else "no candidates"
            return LLMResponse(text="", tool_calls=[], raw=None, finish_reason=str(reason))

        cand = resp.candidates[0]
        parts = cand.content.parts or []
        text = "".join(p.text for p in parts if p.text and not getattr(p, "thought", False)).strip()
        calls = [
            ToolCall(name=p.function_call.name, args=dict(p.function_call.args or {}), id=p.function_call.id)
            for p in parts if p.function_call
        ]
        parsed = None
        if json_schema is not None:
            parsed = resp.parsed if isinstance(resp.parsed, json_schema) else None
            if parsed is None and text:
                try:
                    parsed = json_schema.model_validate_json(text)
                except Exception as exc:
                    raise LLMError(f"Model returned invalid JSON for {json_schema.__name__}: {exc}") from exc
        return LLMResponse(
            text=text, tool_calls=calls, raw=cand.content, parsed=parsed,
            finish_reason=str(cand.finish_reason) if cand.finish_reason else None,
        )

    def usage_summary(self) -> dict:
        return {"calls": dict(self.calls), "tokens": dict(self.tokens)}
