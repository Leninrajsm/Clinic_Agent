"""FastAPI app for the frontend.  Run:  uvicorn app.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import JobManager
from app.api.routes import router
from app.improve.loop import mirror_to_db
from app.runtime import build_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    rt = await build_runtime()
    await rt.ensure_demo_sandbox()
    await mirror_to_db(rt)
    app.state.runtime = rt
    app.state.agent = rt.agent()
    app.state.jobs = JobManager()
    yield


app = FastAPI(title="2care.ai scheduling agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/api/health")
async def health():
    rt = app.state.runtime
    return {"ok": True, "database": rt.repo.backend, "active_policy": rt.policies.active_version(),
            "awaiting_review": [v.version for v in rt.policies.awaiting_review()],
            "models": {"agent": rt.settings.model_agent, "simulator": rt.settings.model_simulator,
                       "judge": rt.settings.model_judge, "analyzer": rt.settings.model_analyzer}}
