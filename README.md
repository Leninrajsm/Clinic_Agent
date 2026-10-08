# Self-improving patient scheduling agent

A patient appointment-scheduling agent (Gemini + tools + MongoDB), an **eval harness** that
scores it against designed scenarios (including the hard ones), and an **improvement loop** that
turns failures into a structured, versioned policy change. The change is kept only if the score
goes up with no regressions.

- **Design note:** [DESIGN_NOTE.md](DESIGN_NOTE.md)
- **AI usage log:** [AI_USAGE.md](AI_USAGE.md)
- **Evidence:** the loop report [Backend/reports/loops/](Backend/reports/loops/), every eval run in
  [Backend/reports/runs/](Backend/reports/runs/), and policy versions in [Backend/policies/](Backend/policies/)

## Result

One loop iteration on 20 scenarios × 3 trials (report: `Backend/reports/loops/20261008-092428-0edd.md`):

| | v1 (hand-written) | v2 (loop-generated) |
|---|---|---|
| Overall | 18/20 | **19/20** |
| Train (analyzer saw these failures) | 13/14 | **14/14** |
| Holdout (never shown to the analyzer) | 5/6 | 5/6 |
| `double_booking_conflict` | 33% | **100%: fixed** |
| Regressions | | none |

The analyzer found that the agent never checked the patient's existing appointments, and added
one general rule. The remaining holdout failure (`weekend_request`) is a different failure class
the analyzer never saw; see the design note.

## Quick start

You need Python 3.11+ and a Gemini API key (https://aistudio.google.com/apikey). A paid-tier key
is recommended: a full eval is about 900 model calls. Node 20+ is only needed for the web UI.

```bash
cd Backend
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -e ".[dev]"
copy .env.example .env          # Windows   (macOS/Linux: cp .env.example .env), then set GEMINI_API_KEY
```

**Run the agent** (terminal chat; shows tool calls, guard decisions and state):

```bash
python -m app.cli chat
```

**Run the eval + improvement loop** (baseline → analyze failures → candidate policy → re-run → gate):

```bash
python -m app.cli loop
```

Those are the two required commands. Everything else is optional:

| Command | What it does |
|---|---|
| `python -m app.cli eval` | One eval run of the active policy, written to `reports/runs/` |
| `python -m app.cli eval --quick` | One trial per scenario (cheap smoke test) |
| `python -m app.cli eval -s double_booking_conflict --policy v1` | One scenario on a chosen policy version |
| `python -m app.cli loop --review` | Human sign-off: a candidate that passes the gate waits for `policy approve vN` / `policy reject vN` |
| `python -m app.cli loop --baseline <run_id>` | Reuse a saved run as the baseline (halves the time) |
| `python -m app.cli policy list` / `policy diff v1 v2` / `policy activate v1` | Inspect versions, roll back instantly |
| `python -m app.cli seed` | Reset the demo clinic's bookings |
| `python -m app.cli models` | List the Gemini models your key can use |
| `pytest` | 57 tests; no API key needed (scripted fake model) |

### Web UI (optional)

```bash
cd Backend && uvicorn app.main:app --reload          # API on :8000
cd Frontend && npm install && npm run dev            # UI on http://localhost:5173
```

- **Assistant:** the patient-facing chat.
- **Evaluations:** runs, per-scenario trial results, checks, judge scores, transcripts and tool activity.
- **Improvement:** start the loop and follow it live (diagnosis, policy diff, regression gate,
  before/after).
- **Policies:** versions, diffs, approve/reject candidates, one-click rollback.

### Demo patients (synthetic)

| Name | Date of birth | Notes |
|---|---|---|
| Maria Lopez | 1988-03-14 | no appointments |
| Emily Chen | 1995-12-01 | has an upcoming dermatology appointment |
| James Carter | 1983-07-09 | has a family-medicine appointment; wife Linda is also a patient |
| Ravi Kumar | 1975-06-02 | no appointments |
| Sam Patel | 1990-01-25 | has an orthopedics appointment |
| John Smith | 1970-04-04 / 1985-09-30 | two patients with the same name |

Try: "Book a dermatology appointment next Friday", "move my appointment", ask about someone
else's appointment, or say "I have chest pain".

### Database

- **No setup needed.** Without `MONGODB_URI`, or if it's unreachable (e.g. a firewall blocks
  port 27017), the app uses an in-memory database seeded with the same synthetic clinic.
- **Reviewers:** the submission form contains a read-write connection string for a dedicated
  MongoDB Atlas database (synthetic data only). Put it in `MONGODB_URI` to run against Atlas.
  A read-only "viewer" login is also provided for browsing in MongoDB Compass: `eval_runs`,
  `policies`, `loop_reports`, `sessions` and `audit_log`.

### Speed, cost and rate limits

`.env.example` defaults are safe for a free-tier key (`LLM_MAX_RPM=12`), which makes a full eval
take about 75 minutes. With a paid key, set:

```
LLM_MAX_RPM=150
LLM_MAX_CONCURRENCY=8
EVAL_CONCURRENCY=6
```

An eval then takes about 10–15 minutes, and the recorded loop cost about ₹325 (2.8M input,
0.4M output tokens). Rate-limit errors are retried with backoff; trials that still fail are
reported as **errors**, never as agent failures. `LLM_CALL_BUDGET` caps calls per command.

## How it works

```
patient msg ─► [safety pre-check] ─► LLM (policy vN + state) ⇄ tools ─► [guards] ─► MongoDB
                code: 911/988 path        tools exposed per stage          code-enforced rules
                                                       │
                                              [grounding check] ─► reply

scenarios/*.yaml ─► harness: seed sandbox on a frozen clock ─► simulated patient ⇄ real agent
                    ─► deterministic checks (DB + tool trace) + transcript judge ─► scores
                    ─► analyzer (train failures only) ─► filtered policy edits ─► vN+1
                    ─► full re-run ─► gate (fixed? no regressions? safety + holdout held?) ─► activate / review
```

| Path | What |
|---|---|
| `Backend/app/agent/` | Orchestrator, state machine, tools, guards, safety pre-check, prompt builder |
| `Backend/app/evals/` | Scenarios, patient simulator, checks, judge, runner, reports |
| `Backend/app/improve/` | Analyzer, patch schema, applier (safety + overfitting filters), gate, loop |
| `Backend/policies/` | `safety_core.md` (locked), `v1.md` (baseline), `v2.md` (loop-generated), `registry.json` |
| `Backend/scenarios/` | `train/` (analyzer sees failures) and `holdout/` (never shown to it) |
| `Backend/fixtures/clinic_seed.json` | Synthetic clinic: 6 doctors, 9 patients, schedules |
| `Frontend/` | React + TypeScript + Tailwind UI |

The recorded run used 20 scenarios. `after_hours_request` (train) was added afterwards for the
next iteration, targeting the failure class the holdout exposed, so the suite now has 21.
