# Stage 7: Verify

**Job:** Check the work against the stage-3 criteria — each one, by its
stated verify method, with the real result shown. This stage answers
"is it done?" with evidence, not confidence.

## Process

1. **Walk the criteria list, one by one.** For each stage-3 criterion,
   run its verify method and record the actual result. Not "should pass" —
   ran it, here's the output. Per-step checks from stage 6 don't count as
   criterion verification; steps verify pieces, this stage verifies the
   whole.

2. **Run the edge cases.** Every stage-3 edge case marked with a criterion
   gets exercised. The "accepted, not handling" ones get left alone — do
   not quietly handle them now.

3. **Check for regressions.** Run the existing tests identified in
   stage 2. The change is not done if it broke something that worked.

4. **Report failures honestly.** A failing criterion means the work
   returns to stage 6 (or, if the criterion itself was wrong, the spec
   gets revised visibly — checkpoint, since spec changes are user
   territory). It does NOT mean the criterion gets reinterpreted until
   the result passes.

5. **Distinguish verified from unverifiable.** Some criteria can't be
   fully checked in the dev environment (load behavior, third-party
   callbacks, production data shapes). Mark them: "unverified here —
   needs <X>." An honest gap beats a false green.

## Output format

```
**Criteria:**
1. <criterion> — ✅/❌ — <evidence: command + result, test name, observation>
2. ...
**Edge cases:** <exercised, results>
**Regressions:** <suite run, result>
**Unverified:** <what couldn't be checked here and what it needs, or "none">
```

## Tier scaling

- **Tier 1:** Run the thing. Show the result. One line: "Ran
  `npm install` per the fixed README — clean exit."
- **Tier 2:** Full output format in chat.
- **Tier 3:** Full output format, appended to the persistent doc. Likely
  includes non-functional checks (migration dry-run, perf measurement)
  where criteria specified them.

## Anti-patterns

- **"It compiles" as verification.** Building/linting clean is a
  precondition, not a criterion check.
- **Verification by re-reading.** Looking at the code and concluding it's
  correct is stage-6 thinking. This stage runs things.
- **Goalpost adjustment.** A criterion that fails gets fixed in the code,
  not reworded in the spec. If the criterion was genuinely wrong, that's
  a visible spec revision, not a quiet edit.
- **Demo-path-only testing.** Verifying the happy path and skipping the
  edge cases that stage 3 explicitly enumerated.
- **Claiming the unverifiable.** Reporting ✅ on something that wasn't
  actually run. The Unverified field exists precisely so this never has
  to happen.
