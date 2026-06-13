# Stage 3: Spec & Acceptance Criteria

**Job:** Convert the problem statement (stage 1) plus current state
(stage 2) into criteria that can be CHECKED, not vibes that can be argued.
Stage 7 will verify against this list item by item — write it so that's
possible.

## Process

1. **Write acceptance criteria as checkable statements.** Each criterion
   must have a concrete verification method: a test that passes, a command
   whose output matches, a behavior observable in a specific way.
   - Weak: "validation works" → Strong: "POST with missing `email` returns
     422 with field-level error message"
   - Weak: "bug is fixed" → Strong: "the repro from stage 2 no longer
     produces the error; regression test added"
   - Weak: "faster" → Strong: "endpoint p95 under 200ms on the test
     dataset" (or, if no target exists, ask — don't invent one)

2. **Enumerate edge cases.** Empty inputs, boundary values, concurrent
   access, the unhappy paths. Each edge case either gets a criterion or an
   explicit "accepted, not handling" note. Silent omission is the failure
   mode.

3. **Draw the scope boundary.** What this change explicitly does NOT do.
   Pull from stage 1's out-of-scope list and add anything stage 2's
   constraints surfaced. This line is what stage 8's trace test measures
   against.

4. **Resolve open questions — all of them.** Anything genuinely unclear
   that survives steps 1–3 triggers the checkpoint: ask the user. A spec
   with open questions does not proceed. But apply the noise filter first:
   if the answer is inferable from the request, codebase, or prior
   context, it's an assumption to state, not a question to ask.

## Output format

```
**Acceptance criteria:**
1. <checkable statement> — verify: <how>
2. <checkable statement> — verify: <how>
**Edge cases:**
- <case> → <criterion # or "accepted, not handling">
**Out of scope:** <explicit boundaries>
**Open questions:** <must be empty to proceed>
```

## Tier scaling

- **Tier 1:** One implicit criterion, stated in passing: "Done = the
  install command in the README runs clean." No formal block.
- **Tier 2:** Full output format in chat. Typically 2–6 criteria.
- **Tier 3:** Full output format, appended to the persistent doc.
  Criteria may include non-functional requirements (performance, security,
  migration safety) — for new projects these are where surprises hide.

## Anti-patterns

- **Unverifiable criteria.** If stage 7 can't check it mechanically or by
  direct observation, it's not a criterion — rewrite it or cut it.
- **Criteria that describe implementation.** "Uses a retry decorator" is
  design (stage 4). Criteria describe observable behavior, not how it's
  achieved.
- **Padding.** Ten criteria where three carry the substance buries the
  signal. Each criterion should be load-bearing.
- **Inventing targets.** No stated performance/limit requirement → don't
  fabricate one to seem rigorous. Ask if it matters, omit if it doesn't.
- **Letting "open questions" leak forward.** Deferring a question to
  "figure out during implementation" is how silent improvisation happens.
  Resolve it here or get the user's answer here.
