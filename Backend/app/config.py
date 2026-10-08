from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
POLICIES_DIR = BACKEND_DIR / "policies"
SCENARIOS_DIR = BACKEND_DIR / "scenarios"
FIXTURES_DIR = BACKEND_DIR / "fixtures"
REPORTS_DIR = BACKEND_DIR / "reports"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    gemini_api_key: str = ""

    mongodb_uri: str = ""
    mongodb_db: str = "twocare_clinic"

    model_agent: str = "gemini-3.8-flash"
    model_simulator: str = "gemini-3.6-flash"
    model_judge: str = "gemini-3.8-flash"
    # Pro only where reasoning quality matters and calls are rare (1-3 per loop); Flash everywhere else.
    model_analyzer: str = "gemini-3.1-pro-preview"
    model_analyzer_fallback: str = "gemini-3.8-flash"  # used if the key can't reach the analyzer model

    llm_max_concurrency: int = 2
    llm_max_rpm: int = 12
    llm_max_retries: int = 5
    llm_call_budget: int = 2500

    clinic_timezone: str = "America/New_York"
    frozen_now: str = ""

    # Evals: trials running at once (the LLM client still enforces LLM_MAX_RPM)
    eval_concurrency: int = 3
    eval_trials: int = 3

    # Agent limits
    # Runaway-loop safety net, not a behaviour constraint: verify + resolve_date + a few searches
    # in one turn is legitimate (6 was too tight; found by the first eval run).
    max_tool_calls_per_turn: int = 10
    max_verification_attempts: int = 3
    max_search_window_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
