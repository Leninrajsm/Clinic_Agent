"""Versioned policy files. The files in policies/ are the source of truth, so every version
(and the diff between them) is visible in git. registry.json records lineage and status."""

import difflib
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.config import POLICIES_DIR

SAFETY_CORE_FILE = "safety_core.md"


class PolicyVersion(BaseModel):
    version: str
    parent: str | None
    status: str  # active | candidate | awaiting_review | rejected | superseded
    file: str
    created_at: str
    notes: str = ""
    patch: dict | list | None = None


class PolicyStore:
    def __init__(self, directory: Path = POLICIES_DIR):
        self.dir = directory
        self.registry_path = directory / "registry.json"

    # ----------------------------------------------------------- registry

    def _load(self) -> dict:
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _save(self, reg: dict) -> None:
        self.registry_path.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")

    def versions(self) -> list[PolicyVersion]:
        return [PolicyVersion(**v) for v in self._load()["versions"]]

    def get(self, version: str) -> PolicyVersion:
        for v in self.versions():
            if v.version == version:
                return v
        raise KeyError(f"Unknown policy version {version!r}")

    def active_version(self) -> str:
        return self._load()["active"]

    # ----------------------------------------------------------- content

    def text(self, version: str) -> str:
        return (self.dir / self.get(version).file).read_text(encoding="utf-8")

    def safety_core(self) -> str:
        return (self.dir / SAFETY_CORE_FILE).read_text(encoding="utf-8")

    def diff(self, old: str, new: str) -> str:
        return "".join(difflib.unified_diff(
            self.text(old).splitlines(keepends=True), self.text(new).splitlines(keepends=True),
            fromfile=f"{old}.md", tofile=f"{new}.md",
        ))

    # ----------------------------------------------------------- lifecycle

    def next_version(self) -> str:
        return f"v{max(int(v.version.lstrip('v')) for v in self.versions()) + 1}"

    def create_candidate(self, parent: str, text: str, patch: dict | list | None, notes: str = "") -> PolicyVersion:
        reg = self._load()
        version = self.next_version()
        (self.dir / f"{version}.md").write_text(text, encoding="utf-8")
        entry = PolicyVersion(
            version=version, parent=parent, status="candidate", file=f"{version}.md",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), notes=notes, patch=patch,
        )
        reg["versions"].append(entry.model_dump())
        self._save(reg)
        return entry

    def set_status(self, version: str, status: str) -> None:
        reg = self._load()
        for v in reg["versions"]:
            if v["version"] == version:
                v["status"] = status
        self._save(reg)

    def awaiting_review(self) -> list[PolicyVersion]:
        return [v for v in self.versions() if v.status == "awaiting_review"]

    def approve(self, version: str) -> None:
        """Human sign-off on a candidate that already passed the regression gate."""
        if self.get(version).status != "awaiting_review":
            raise ValueError(f"{version} is not awaiting review (status: {self.get(version).status}). "
                             "Use 'policy activate' to switch versions directly.")
        self.activate(version)

    def reject(self, version: str) -> None:
        if version == self.active_version():
            raise ValueError(f"{version} is live; activate another version first.")
        self.set_status(version, "rejected")

    def activate(self, version: str) -> None:
        reg = self._load()
        self.get(version)  # validates it exists
        for v in reg["versions"]:
            if v["version"] == reg["active"] and v["version"] != version:
                v["status"] = "superseded"
            if v["version"] == version:
                v["status"] = "active"
        reg["active"] = version
        self._save(reg)
