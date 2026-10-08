from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.db.seed import clinic_info, load_fixture
from app.evals.report import list_runs, load_run, persist_run
from app.evals.runner import run_suite
from app.evals.scenarios import load_scenarios
from app.improve.loop import list_loops, load_loop, mirror_to_db, run_loop
from app.runtime import DEMO_SANDBOX

router = APIRouter(prefix="/api")


def _rt(request: Request):
    return request.app.state.runtime


# ------------------------------------------------------------------ chat

class NewSession(BaseModel):
    policy_version: str | None = None


class PatientMessage(BaseModel):
    text: str


@router.post("/sessions")
async def create_session(body: NewSession, request: Request):
    rt = _rt(request)
    agent = request.app.state.agent
    version = body.policy_version or rt.policies.active_version()
    try:
        rt.policies.get(version)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    session = await agent.start_session(DEMO_SANDBOX, version)
    return {"session_id": session.id, "greeting": agent.greeting(), "policy_version": version,
            "database": rt.repo.backend, "model": agent.model}


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: PatientMessage, request: Request):
    if not body.text.strip():
        raise HTTPException(400, "Empty message")
    try:
        return await request.app.state.agent.respond(session_id, body.text.strip()[:2000])
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    rt = _rt(request)
    doc = await rt.repo.get_session(session_id)
    if not doc:
        raise HTTPException(404, "Unknown session")
    audit = await rt.repo.audit_for_session(session_id)
    return {"session": doc, "audit": [{k: v for k, v in e.items() if k != "_id"} for e in audit]}


@router.post("/demo/reset")
async def reset_demo(request: Request):
    return await _rt(request).ensure_demo_sandbox(reset=True)


@router.get("/clinic")
async def clinic(request: Request):
    """Clinic info plus the synthetic test identities, so a demo user knows who to 'be'."""
    rt = _rt(request)
    clock = rt.clock
    patients = []
    for p in load_fixture()["patients"]:
        appts = await rt.repo.patient_appointments(DEMO_SANDBOX, p["id"], after=clock.now())
        patients.append({"name": f"{p['first_name']} {p['last_name']}", "dob": p["dob"],
                         "appointments": [f"{a.specialty}, {clock.fmt(a.start)}" for a in appts]})
    return {"clinic": clinic_info(), "providers": load_fixture()["providers"], "patients": patients,
            "now": clock.now().isoformat(), "database": rt.repo.backend}


# ------------------------------------------------------------------ evals + loop

class EvalRequest(BaseModel):
    policy_version: str | None = None
    trials: int | None = None
    scenario_ids: list[str] | None = None


class LoopRequest(BaseModel):
    trials: int | None = None
    scenario_ids: list[str] | None = None
    max_attempts: int = 3
    iterations: int = 1
    baseline_run_id: str | None = None
    review: bool = False  # hold a passing candidate for human approval instead of activating it


@router.get("/scenarios")
async def scenarios():
    return [s.model_dump() for s in load_scenarios()]


@router.get("/evals/runs")
async def runs():
    return list_runs()


@router.get("/evals/runs/{run_id}")
async def run_detail(run_id: str):
    try:
        return load_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


def _ensure_idle(request: Request):
    busy = request.app.state.jobs.running()
    if busy:
        raise HTTPException(409, f"A {busy.kind} job is already running ({busy.id}).")


@router.post("/evals/runs")
async def start_eval(body: EvalRequest, request: Request):
    _ensure_idle(request)
    rt = _rt(request)
    version = body.policy_version or rt.policies.active_version()
    scs = load_scenarios(ids=body.scenario_ids)
    trials = max(1, min(body.trials or rt.settings.eval_trials, 5))

    async def work(emit):
        result = await run_suite(rt, version, scs, trials, emit)
        await persist_run(rt.repo, result)
        return {"run_id": result.run_id, "summary": result.summary}

    return request.app.state.jobs.start("eval", work).info()


@router.post("/loop")
async def start_loop(body: LoopRequest, request: Request):
    _ensure_idle(request)
    rt = _rt(request)
    trials = max(1, min(body.trials or rt.settings.eval_trials, 5))

    async def work(emit):
        report = await run_loop(rt, trials, body.scenario_ids, body.max_attempts, body.iterations,
                                body.baseline_run_id, emit, review=body.review)
        return {"loop_id": report.loop_id, "outcome": report.outcome, "final_version": report.final_version,
                "awaiting_review": report.awaiting_review}

    return request.app.state.jobs.start("loop", work).info()


@router.get("/loops")
async def loops():
    return list_loops()


@router.get("/loops/{loop_id}")
async def loop_detail(loop_id: str):
    try:
        return load_loop(loop_id)
    except FileNotFoundError:
        raise HTTPException(404, "Unknown loop")


@router.get("/jobs/{job_id}")
async def job(job_id: str, request: Request):
    j = request.app.state.jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Unknown job")
    return {**j.info(), "events": j.events}


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    j = request.app.state.jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Unknown job")
    return StreamingResponse(j.stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ policies

@router.get("/policies")
async def policies(request: Request):
    store = _rt(request).policies
    return {"active": store.active_version(), "versions": [v.model_dump() for v in store.versions()]}


@router.get("/policies/{version}")
async def policy(version: str, request: Request):
    store = _rt(request).policies
    try:
        return {**store.get(version).model_dump(), "content": store.text(version)}
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@router.get("/policy-diff")
async def policy_diff(old: str, new: str, request: Request):
    try:
        return {"diff": _rt(request).policies.diff(old, new)}
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@router.post("/policies/{version}/approve")
async def approve(version: str, request: Request):
    _ensure_idle(request)
    rt = _rt(request)
    try:
        rt.policies.approve(version)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    await mirror_to_db(rt)
    return {"active": version}


@router.post("/policies/{version}/reject")
async def reject(version: str, request: Request):
    rt = _rt(request)
    try:
        rt.policies.reject(version)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    await mirror_to_db(rt)
    return {"rejected": version}


@router.post("/policies/{version}/activate")
async def activate(version: str, request: Request):
    _ensure_idle(request)
    rt = _rt(request)
    try:
        rt.policies.activate(version)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    await mirror_to_db(rt)
    return {"active": version}
