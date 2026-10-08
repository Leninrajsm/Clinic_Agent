"""Scenario files: who the simulated patient is, what the clinic looks like, and what success means."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from app.config import SCENARIOS_DIR
from app.db.seed import SeedOverrides

# Every eval runs on this frozen clinic-local time (a Monday) so dates resolve identically.
EVAL_NOW = "2026-10-12T09:00:00"


class CheckSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    critical: bool = False

    @property
    def params(self) -> dict:
        return dict(self.model_extra or {})


class RubricItem(BaseModel):
    id: str
    critical: bool = False  # critical rubric items fail the trial if scored below 4/5


class Scenario(BaseModel):
    id: str
    split: Literal["train", "holdout"]
    category: str
    description: str
    persona: str
    opening: str | None = None  # fixed first patient message (reduces run-to-run variance)
    max_turns: int = 12
    now: str = EVAL_NOW
    seed: SeedOverrides = SeedOverrides()
    faults: dict[str, int] = {}
    checks: list[CheckSpec]
    rubric: list[RubricItem] = []

    @field_validator("rubric", mode="before")
    @classmethod
    def _rubric(cls, v):
        return [{"id": x} if isinstance(x, str) else x for x in v or []]


def load_scenarios(directory: Path = SCENARIOS_DIR, ids: list[str] | None = None,
                   split: str | None = None) -> list[Scenario]:
    out = []
    for path in sorted(directory.glob("*/*.yaml")):
        sc = Scenario(**yaml.safe_load(path.read_text(encoding="utf-8")))
        if sc.split != path.parent.name:
            raise ValueError(f"{path}: split '{sc.split}' does not match folder '{path.parent.name}'")
        out.append(sc)
    seen = [s.id for s in out]
    if len(seen) != len(set(seen)):
        raise ValueError("Duplicate scenario ids")
    if ids:
        unknown = set(ids) - set(seen)
        if unknown:
            raise ValueError(f"Unknown scenario ids: {sorted(unknown)}")
        out = [s for s in out if s.id in ids]
    if split:
        out = [s for s in out if s.split == split]
    return out
