# Stage 5: Plan & Decompose

**Job:** Break the design into ordered steps where each step has its own
verify check. A good plan lets implementation loop independently — finish
a step, verify it, move on — without needing the user or re-deriving the
approach mid-flight.

## Process

1. **Decompose into steps.** Each step should be:
   - **Small enough to verify on its own** — if a step can't be checked
     until three steps later, merge or re-split.
   - **Ordered by dependency**, with risky or uncertain steps EARLY. If a
     step might invalidate the design (an API doesn't behave as assumed,
     a library can't do the thing), front-load it — fail fast while the
     sunk cost is one step, not seven.

2. **Attach a verify check to every step.** The CLAUDE.md format:
   ```
   1. <step> → verify: <check>
   2. <step> → verify: <check>
   ```
   A check is a command, a test run, or a concrete observation. "It should
   work" is not a check. Where practical, the check is a test written
   BEFORE the step's code (repro test for bugs, failing test for new
   behavior).

3. **Map criteria coverage.** Every stage-3 criterion should be satisfied
   by some step's verify check. A criterion no step covers means the plan
   is incomplete; a step no criterion motivates means the plan has scope
   creep.

4. **Track the plan in a tool.** Use TodoWrite for session-scoped work.
   Use Linear when the work crosses sessions, involves the agents, or the
   user asks — and per working agreement, get explicit authorization
   before filing tickets.

## Output format

The step list itself, in the step → verify format, posted in chat and
mirrored into TodoWrite. For tier 3, also appended to the persistent doc.

## Tier scaling

- **Tier 1:** No plan — the task IS one step, and its verify check is
  stage 7. If you find yourself wanting a plan, the tier is wrong.
- **Tier 2:** 3–8 steps, TodoWrite, in chat.
- **Tier 3:** Full decomposition; consider milestones (groups of steps
  that produce something demonstrable). Linear if cross-session.

## Anti-patterns

- **Steps without checks.** A bare step list is a hope list. Every arrow
  needs a right-hand side.
- **Verification ghetto.** One giant "test everything" step at the end.
  Verification is distributed per-step or it isn't a decomposition.
- **Risk buried late.** The unknown-unknowns step scheduled last, after
  seven steps of sure-thing work has been built on top of the assumption
  it tests.
- **Over-decomposition.** Twenty micro-steps for an afternoon's work is
  plan theater. Steps exist to create verify points, not to look thorough.
- **Plan as ritual.** If reality diverges from the plan at stage 6, the
  plan gets revised visibly (checkpoint condition 4) — not silently
  abandoned while the todo list rots.
