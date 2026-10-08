from dataclasses import dataclass, field

from app.agent.state import Session
from app.clinic.dates import Clock
from app.config import Settings
from app.repo.clinic_repo import ClinicRepository


@dataclass
class ToolContext:
    """Everything a tool or guard may touch during one patient turn."""

    repo: ClinicRepository
    clock: Clock
    settings: Settings
    session: Session
    committed_this_turn: list[str] = field(default_factory=list)
    faults: dict[str, int] = field(default_factory=dict)  # tool name -> remaining forced failures

    @property
    def state(self):
        return self.session.state

    @property
    def sandbox_id(self) -> str:
        return self.session.sandbox_id
