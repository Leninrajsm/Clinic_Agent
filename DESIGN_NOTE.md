# Design note

## Key choices

- **Safety lives in code; behaviour lives in a versioned policy.** Guards check every tool call:
  - tools are exposed per conversation stage, and the patient ID comes only from verified state
  - only slots this session actually found can be held, and patients act only on their own appointments
  - a commit must come in a later turn than the hold, so the patient has to say yes first
  - a red-flag pre-check answers emergencies before any LLM call
  - a grounding check blocks "you're booked" unless a commit really happened

  The loop can only edit the policy text, never these rules or the locked `safety_core.md`, so a
  bad policy can make the agent less helpful but not unsafe.
- **No agent framework.** A ~150-line orchestrator keeps the guard layer, state transitions and
  exact prompt (safety core + policy vN + state) explicit and unit-tested. For many flows in
  production I'd consider LangGraph.
- **Explicit state, deterministic dates.** A `SessionState` (stage, verified patient, slots found,
  pending action) is rendered into the prompt each turn. "Next Friday" on a Monday is flagged
  as ambiguous by code, not guessed.
- **Rubric: deterministic checks (70%) + transcript judge (30%).** The judge only reads the
  transcript, so it's blind to whether a booking happened, on which date, or whether data was
  read before verification. The checks cover that from the database and tool trace. A critical
  check or critical rubric item fails a trial outright. LLMs vary, so each scenario runs 3 trials
  and passes on majority.

## How the loop works

Baseline eval (20 scenarios: 14 train, 6 holdout, × 3 trials, each on a fresh sandbox clinic with a
frozen clock) → the analyzer (Gemini Pro) sees **train failures only** and returns structured
proposals (root cause, `add_rule`/`replace_rule` edits, targets, or a `needs_code_change` ticket)
→ an applier refuses edits that weaken safety or overfit (patient names, dates, scenario ids) →
candidate vN+1 → full re-run → **gate**: targets improved, no regressions (suspected regressions
re-run to rule out noise), safety held, holdout not worse → with `--review`, held for human
approval; otherwise activated. Every version is kept; rollback is one command.

## Before / after (loop `20261008-092428-0edd`)

| | v1 (hand-written) | v2 (loop) |
|---|---|---|
| Overall | 18/20 (mean 0.898) | **19/20** (mean 0.948) |
| Train | 13/14 | **14/14** |
| Holdout (never shown to the analyzer) | 5/6 | 5/6 |
| `double_booking_conflict` | 1/3 trials | **3/3: fixed** |
| `narrow_time_window` | 2/3 | 3/3 (side benefit) |

Diagnosis: the agent never checked the patient's schedule before offering slots. Fix: one
general rule ("check `list_my_appointments`; never offer or book an overlapping time"). No
regressions. The remaining holdout failure, `weekend_request`, is a class the analyzer never saw:
when the clinic is closed, the agent explains the hours but doesn't search for alternatives. I
added a train scenario of that class (`after_hours_request`) for the next iteration and kept
`weekend_request` in holdout so it stays an unseen test.

**What real runs taught me.** The first eval showed 3 failures; 2 were bugs in my *harness* (the
patient's final "yes" was never delivered) and 1 was a tool-call cap set below legitimate use. I
fixed those by hand before running the loop, otherwise it would have "fixed" failures that
didn't exist. When v1 then passed everything, I added harder, realistic scenarios rather than
weakening v1. The loop took ~2.5 h at free-tier rate limits (~25 min at paid limits) and cost
about ₹325.

## For a real clinic

Turn production failures into scenarios: flag calls that ended with no outcome, showed
frustration, or scored low on the live judge, draft a de-identified scenario, and have a human
approve it, so every real mistake becomes a permanent regression test. Make the `--review`
sign-off mandatory and roll new policies out gradually (shadow, then a share of calls).

## AI vs my judgment

I used Claude Code throughout as a pair programmer: it drafted most of the code and tests. I
made the calls that shaped the project: the stack (Python, TypeScript, MongoDB Atlas, Gemini),
giving reviewers real database access through limited users, Pro only for the analyzer where
quality matters and Flash everywhere else, and a human approval step so the loop can't push a
policy live on its own. I worked through the scenario set, reviewed what each one tests, and
directed changes to it. When the first runs failed, I went through each failure before trusting
the score; two turned out to be harness bugs. I wanted to train on the weekend case directly;
keeping it as an unseen holdout and adding a different train scenario of the same class was the
better call, and I took it. Details in [AI_USAGE.md](AI_USAGE.md).
