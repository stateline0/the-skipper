# Stage 6: Implement

**Job:** Execute the plan, one step at a time, verifying as you go.
Discipline here is mostly about what you DON'T do: don't touch what the
plan doesn't touch, don't add what the spec doesn't ask for, don't
improvise silently when reality disagrees with the plan.

## Process

1. **Work the plan step by step.** Complete a step, run its verify check,
   mark it done in TodoWrite, move to the next. Don't batch five steps and
   verify at the end — that converts a decomposition back into a blob.

2. **Stay surgical.**
   - Touch only files on the stage-4 list. Need another file? That's a
     deviation — narrate it (see #4).
   - Match the conventions recorded in stage 2, even where you'd choose
     differently.
   - Don't improve adjacent code, reformat untouched lines, or rewrite
     comments you pass by. Diff noise is review cost.
   - Clean up only your own orphans: imports, variables, and functions
     that YOUR change made unused get removed; pre-existing dead code gets
     added to "Noticed but not touching," never deleted.

3. **Hold the spec line.** Mid-implementation ideas — a nice abstraction,
   a config option, handling for a case nobody specified — are spec
   changes, not coding decisions. Note them for stage 8's handoff;
   don't build them.

4. **Narrate every deviation.** When reality disagrees with the plan,
   say so in the moment, visibly:
   - *Small* (different helper, extra file for the same approach): one
     line — "Deviation: also touching `utils.py`, the parser lives there
     not in `main.py`" — then proceed.
   - *Material* (approach won't work, spec was wrong, scope grew): stop.
     This is checkpoint condition 4 — present what changed and the revised
     plan before continuing.
   The test: would the user be surprised to learn this at review? Then it
   gets narrated now.

5. **Keep commits honest.** Small, coherent commits with messages that say
   what actually changed and why — including deviations. No "fix stuff."

## Output format

No formal artifact — the outputs are the code, the updated TodoWrite, and
deviation narrations inline as they happen.

## Tier scaling

- **Tier 1:** Make the change, matching local style. Surgical rules apply
  at FULL strength — small edits to existing code are where adjacent
  "improvements" are most tempting and least wanted.
- **Tier 2/3:** Process above. For tier 3, material deviations also get
  recorded in the persistent doc, since they're design history.

## Anti-patterns

- **The helpful drive-by.** Fixing a typo in a comment, renaming a vague
  variable, reformatting a function you scrolled past. Every one is an
  unrequested diff line that dilutes review.
- **Silent substitution.** The planned approach hit friction, so a
  different one got built without anyone hearing about it. The code may
  even be right — the silence is the failure.
- **Speculative hardening.** try/except around code that can't throw,
  validation for inputs that can't occur, defaults for configs nobody can
  set. Error handling traces to criteria like everything else.
- **Batch-then-pray.** Implementing the whole plan before running any
  verify check. Per-step verification is what makes failures cheap to
  localize.
- **TodoWrite drift.** The list says step 3, the code says step 6,
  and two new steps happened that the list never heard about. The plan
  is a live instrument, not an opening ceremony.
