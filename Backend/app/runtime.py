"""Wires the components together for the CLI and the API."""

import logging
from dataclasses import dataclass

from app.agent.orchestrator import ClinicAgent
from app.clinic.dates import Clock
from app.config import Settings, get_settings
from app.db.seed import seed_sandbox
from app.llm.base import LLMClient
from app.policy.store import PolicyStore
from app.repo.clinic_repo import ClinicRepository
from app.repo.store import open_store

DEMO_SANDBOX = "demo"


@dataclass
class Runtime:
    settings: Settings
    repo: ClinicRepository
    llm: LLMClient
    clock: Clock
    policies: PolicyStore

    def agent(self, clock: Clock | None = None) -> ClinicAgent:
        return ClinicAgent(self.repo, self.llm, clock or self.clock, self.settings, self.policies)

    async def ensure_demo_sandbox(self, reset: bool = False) -> dict | None:
        if reset or not await self.repo.sandbox_exists(DEMO_SANDBOX):
            return await seed_sandbox(self.repo, DEMO_SANDBOX, self.clock)
        return None


async def build_runtime(settings: Settings | None = None, llm: LLMClient | None = None) -> Runtime:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = settings or get_settings()
    store = await open_store(settings.mongodb_uri, settings.mongodb_db)
    if llm is None:
        from app.llm.gemini import GeminiClient  # imported lazily so tests don't need the SDK configured
        llm = GeminiClient(settings)
    return Runtime(
        settings=settings,
        repo=ClinicRepository(store),
        llm=llm,
        clock=Clock.from_iso(settings.clinic_timezone, settings.frozen_now or None),
        policies=PolicyStore(),
    )
