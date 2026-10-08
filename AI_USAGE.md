# AI usage log

I built this with Claude Code as a pair programmer. This log records who proposed each decision
and how I decided, and feeds the "AI vs my judgment" section of [DESIGN_NOTE.md](DESIGN_NOTE.md).

| Decision | Proposed by | My call |
|---|---|---|
| Python backend, TypeScript frontend, separate Backend/ and Frontend/ folders | Me | My starting requirement |
| Gemini as the LLM, MongoDB Atlas as the database | Me | My starting requirement |
| In-memory DB fallback | AI | Accepted, so a reviewer can run it with only a Gemini key |
| Reviewers get real access to the Atlas data | Me | I wanted reviewers to see the actual database, not only a fallback. Done with limited reviewer/viewer users; credentials go in the form, never in git |
| Safety rules in code, a locked safety core the loop can't edit | AI | Accepted; I wanted it clear that a bad policy can't make the agent unsafe |
| Deterministic date resolution ("next Friday" flagged as ambiguous) | AI | Accepted |
| Keep the baseline policy reasonable, not weakened to create failures | AI | Agreed; failures had to be real |
| Scenario suite (train/holdout, hard cases, checks) | Drafted with AI | I worked through every scenario, reviewed what each one tests and how it's scored, and directed changes (the weekend/after-hours case below) |
| Holdout scenarios hidden from the analyzer; anti-overfitting filter on edits | AI | Accepted after working through why a fix must generalise, not memorise |
| Model choice | Me | I first asked to move everything to Flash for cost, then settled on Pro only for the analyzer (1–3 calls per loop) with a Flash fallback, Flash everywhere else |
| Prepaid Gemini credits instead of open-ended billing | Me | Keeps spend capped |
| Human approval before a policy goes live (`--review`) | Me | I asked how the developer stays in control after the loop writes v2; this option came out of that |
| Weekend failure | Me, refined by AI | I wanted to train the agent on the weekend case. Moving the holdout scenario into train would have made it useless as an unseen test, so a different train scenario of the same class was added instead |
| Patient-facing Assistant page, clinic colour theme (#B3D7E0) | Me | The team uses the assistant like a patient would, so debug panels and labels belong on the other pages |
| Video walks through the recorded loop instead of re-running it live | Me | The full loop took ~2.5 h; the recorded run is the real evidence, and the fix is shown live in the chat |

## Where AI wrote code
Claude Code drafted the code across the data layer, agent, guards, eval harness, improvement
loop, API, UI and tests. I ran everything against the real model and database, reviewed the
results and transcripts, and directed the fixes below.

## Found by real runs
- **First quick eval (v1: 12/15): 2 of 3 failures were harness bugs.** The simulated patient said
  "yes, confirm" and ended the chat in the same message, and the runner never delivered that "yes".
  Fixed so the final patient message always reaches the agent, with a regression test. The third
  failure was a **tool-call cap set too tight** (6 per turn; raised to 10). The agent had already
  found the right doctor when the cap cut it off. Lesson: read failing transcripts before trusting a
  score, because the evaluator needs testing too.
- **v1 then passed 15/15**, so the suite was too easy to drive improvement. Five harder, realistic
  scenarios were added (new patient, which appointment, double booking, narrow time window, weekend
  request) rather than weakening v1. v1 then scored 18/20 at 3 trials.
- **Single trials mislead:** `no_slots_available` failed once in a quick run but passed 3/3 at
  baseline, while `double_booking_conflict` "passed" once but really failed 2 of 3. That's why the
  loop uses 3 trials and a majority vote.
- **The loop closed:** the analyzer diagnosed the double booking (the agent never checked the
  patient's schedule) and added one general rule. v2: 19/20, train 14/14, no regressions.
- **The holdout exposed a gap the train set didn't cover** (`weekend_request`: clinic closed, no
  alternatives searched). Added `after_hours_request` to train for the next iteration.
- **UI bug:** an effect returned the Promise from `scrollIntoView()` in newer browsers, which
  crashed the chat page. I found it by clicking through the UI; fixed.
