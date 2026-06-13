---
name: dev-process
description: Structured development process for building, fixing, or changing code in this project. Use this skill whenever the user requests any code change — a new feature, a bug fix, a refactor, a config change, or a new project — even if they don't mention "process." It classifies the task into a tier and walks the appropriate stages, pausing for user input only at defined checkpoints. Do not skip this skill because a task seems simple; the skill itself decides how much ceremony applies.
---

# Development Process Orchestrator

Walks every dev task through the right stages at the right weight. The goal:
no stage happens invisibly. Compressed is fine; skipped is not.

## Step 1: Classify the tier

Before anything else, state the tier and why. If ambiguous, ask.

| Tier | Examples | Stages |
|------|----------|--------|
| 1 — Quick fix | Typo, one-liner, config tweak, copy change | 1, 2, 6, 7, 8 (compressed) |
| 2 — Feature / change | New endpoint, behavior change, multi-file edit | All stages, artifacts inline in chat |
| 3 — Project / major feature | New app, new subsystem, architectural change | All stages, artifacts as files in repo |

When in doubt between tiers, classify UP. The user can talk you down.

## Step 2: Walk the stages

Read each stage file when you reach that stage — not before.
Every stage produces its output visibly in the conversation, then proceeds —
stopping for user input only per the checkpoint rules below.

| # | Stage | File | Output |
|---|-------|------|--------|
| 1 | Intake & Framing | stages/01-intake.md | Problem statement + assumptions list |
| 2 | Context Gathering | stages/02-context.md | Current-state summary, conventions to match |
| 3 | Spec & Criteria | stages/03-spec.md | Verifiable acceptance criteria, scope boundaries |
| 4 | Design Proposal | stages/04-design.md | Approach, files touched, simpler alternative considered |
| 5 | Plan & Decompose | stages/05-plan.md | Ordered steps, each with a verify check |
| 6 | Implement | stages/06-implement.md | Code, deviations narrated |
| 7 | Verify | stages/07-verify.md | Criteria from stage 3 checked one by one |
| 8 | Review & Handoff | stages/08-review.md | Diff trace check, handoff note |

Tier 1 path: stage 1 is one sentence + assumptions; stage 2 is reading the
file you're about to touch; implement, verify, then a one-line wrap-up
(trace test + anything noticed along the way). Surgical-change rules
(below) still apply in full.

## Hard rules (apply at every tier)

These are non-negotiable regardless of ceremony level:

1. **Never pick an interpretation silently.** Multiple readings → present them (stage 1).
2. **Unclear → stop and ask.** A spec with open questions cannot proceed (stage 3).
3. **Every design names the simpler alternative**, even if rejected (stage 4).
4. **Surgical changes only.** Touch only what the request requires. Don't improve
   adjacent code. Match existing style. Remove only orphans YOUR change created.
   Mention pre-existing dead code; never delete it unasked (stages 2, 6, 8).
5. **No speculative anything.** No unrequested features, abstractions for
   single-use code, or configurability nobody asked for (stages 4, 6, 8).
6. **Criteria must be checkable.** "Make it work" is not a criterion (stage 3).
7. **Deviations get narrated.** Mid-implementation urge to add or change scope →
   say so, don't silently build (stage 6).
8. **The trace test at review:** every changed line traces to the request (stage 8).

## Checkpoints (when to stop and ask)

Default is to proceed through stages without waiting for approval. Stop and
ask ONLY when one of these is true:

1. **Multiple plausible interpretations** of the request exist and the choice
   between them changes the outcome. Present the readings; let the user pick.
2. **An open question survives stage 3.** A spec with unresolved questions
   cannot proceed — ask, don't guess.
3. **A design decision meaningfully trades off** things the user cares about
   (scope, complexity, cost, reversibility) and their preference isn't
   inferable from prior context or stated goals.
4. **Mid-implementation discovery changes the plan** — the spec was wrong,
   the scope grew, or the approach won't work as designed.

If none apply, present the stage output and keep moving. Do NOT manufacture
questions to seem thorough — a question whose answer is already inferable
from the request or the codebase is noise, not alignment.

If the user says "skip the process" or equivalent, honor it — but the hard
rules above still apply.
