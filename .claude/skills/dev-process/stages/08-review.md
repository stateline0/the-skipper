# Stage 8: Review & Handoff

**Job:** Audit the finished diff against everything promised upstream,
then leave the work in a state the next session can pick up cold. This is
where the chain's contracts get enforced — and where the user gets the
honest summary.

## Process

1. **Run the trace test.** Walk the diff. Every changed line traces to the
   request via a stage-3 criterion or a narrated deviation. Lines that
   trace to nothing — drive-by fixes, speculative additions, format churn —
   get reverted before handoff, not apologized for in it.

2. **Audit against the stage-4 file list.** Files changed but not on the
   list (and not narrated)? Files on the list but untouched? Either is a
   finding: revert, narrate retroactively with explanation, or flag.

3. **Run the simplicity pass.** Read the diff as the senior engineer from
   stage 4 would: abstractions serving one caller, configurability nobody
   asked for, 200 lines doing 50 lines of work. Found late, this is a
   judgment call — flag it in the handoff with a rework estimate rather
   than silently rewriting verified code.

4. **Check commit hygiene.** Commits coherent, messages honest, deviations
   reflected. Squash or reword if the history misrepresents what happened.

5. **Write the handoff note.** The artifact the next session (or the user,
   or an agent) starts from:

```
**Done:** <what shipped, mapped to criteria>
**Deviations from plan:** <what changed and why, or "none">
**Deferred / ideas not built:** <stage-6 parking lot items, spec-change
  candidates — explicitly NOT done>
**Noticed but not touching:** <dead code, adjacent bugs — carried from
  stage 2 + anything found since>
**Known rough edges:** <unverified criteria from stage 7, shortcuts taken,
  follow-ups recommended>
```

## Tier scaling

- **Tier 1:** Trace test + one-line summary: "Changed the one line, ran
  it, clean." Anything noticed along the way still gets mentioned.
- **Tier 2:** Full process; handoff note in chat.
- **Tier 3:** Full process; handoff note closes out the persistent doc.
  Update Linear if tickets exist (with authorization, per working
  agreement).

## Anti-patterns

- **Review as victory lap.** Summarizing what went well instead of
  auditing what changed. This stage exists to catch problems, and finding
  one is the stage working.
- **Fixing during review.** Finding an issue → it goes through the loop
  (back to stage 6, verify again), not patched inline with no
  verification. Review that edits is implementation without a net.
- **Burying the rough edges.** The handoff note's value is concentrated in
  its least flattering sections. "Done: everything, no notes" on
  non-trivial work is a red flag, not a good result.
- **Inflated handoff.** Claiming criteria met that stage 7 marked
  unverified, or describing deferred items ambiguously enough to read as
  done. The note is read by someone who wasn't here — write for them.
- **Orphaned parking lot.** Stage-6 ideas and "noticed but not touching"
  items that die in the chat scroll. The handoff note is their exit —
  every item either lands there or was consciously dropped.
