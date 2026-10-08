"""Background jobs (eval runs, improvement loops) with an event log that clients stream over SSE."""

import asyncio
import json
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable


class Job:
    def __init__(self, kind: str):
        self.id = f"job_{uuid.uuid4().hex[:8]}"
        self.kind = kind
        self.status = "running"
        self.events: list[dict] = []
        self.result: Any = None
        self.error: str | None = None
        self.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._changed = asyncio.Event()

    def push(self, event: dict) -> None:
        self.events.append(event)
        self._changed.set()

    def info(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "created_at": self.created_at,
                "events": len(self.events), "result": self.result, "error": self.error}

    async def stream(self) -> AsyncIterator[str]:
        sent = 0
        while True:
            while sent < len(self.events):
                yield f"data: {json.dumps(self.events[sent], default=str)}\n\n"
                sent += 1
            if self.status != "running":
                yield f"event: end\ndata: {json.dumps(self.info(), default=str)}\n\n"
                return
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def running(self) -> Job | None:
        return next((j for j in self.jobs.values() if j.status == "running"), None)

    def start(self, kind: str, work: Callable[[Callable[[dict], None]], Awaitable[Any]]) -> Job:
        job = Job(kind)
        self.jobs[job.id] = job

        async def runner():
            try:
                job.result = await work(job.push)
                job.status = "done"
            except Exception as exc:
                job.error = f"{type(exc).__name__}: {exc}"
                job.status = "error"
                job.push({"type": "job_error", "error": job.error, "trace": traceback.format_exc()[-2000:]})
            job._changed.set()

        job._task = asyncio.create_task(runner())
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)
