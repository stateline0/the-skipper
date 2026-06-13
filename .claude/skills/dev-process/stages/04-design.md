# Stage 4: Design Proposal

**Job:** Decide HOW, visibly. Name the approach, what it touches, what it
trades off, and what simpler option was considered. This is the cheapest
stage to kill complexity — bad design caught here costs a paragraph; caught
at stage 8 it costs a rewrite.

## Process

1. **State the approach.** The mechanism in plain terms: what components
   are added or changed, how data flows, what the change looks like from
   the outside. Concrete enough that someone else could implement from it.

2. **List files touched.** Every file the implementation will create or
   modify, with a one-line reason each. This list is the contract stage 8
   audits against — a file changed at stage 6 that isn't on this list is a
   narrated deviation, not a quiet addition.

3. **Name the simpler alternative — always.** What's the less clever
   version of this? Fewer files, no new dependency, no abstraction?
   Either adopt it or state concretely why it fails a stage-3 criterion.
   "Simpler alternative: none found" is allowed but must be earned —
   inline change vs. new module, hardcode vs. configure, extend vs.
   rewrite are almost always live options.

4. **Run the senior-engineer test.** Does anything in this design lack a
   traceable line to a stage-3 criterion? New abstractions for single-use
   code, configurability nobody asked for, error handling for impossible
   states, speculative extension points — cut them now.

5. **Surface real tradeoffs.** If the design picks between things the user
   cares about (scope, complexity, cost, reversibility) and their
   preference isn't inferable → checkpoint: present the options with your
   recommendation and let them choose. If one option is clearly right,
   choose it and note why — don't checkpoint for theater.

## Output format

```
**Approach:** <mechanism, 2-6 sentences>
**Files touched:**
- <path> — <why>
**Simpler alternative considered:** <what, and why rejected — or why adopted>
**New dependencies:** <packages/services added, or "none">
**Tradeoffs:** <what this gives up, or "none material">
```

## Tier scaling

- **Tier 1:** Skipped — the fix IS the design. If a "quick fix" turns out
  to need a design decision, it was misclassified; bump the tier.
- **Tier 2:** Full output format in chat. Approach section often 2-3
  sentences.
- **Tier 3:** Full output format, appended to the persistent doc, plus
  alternatives rejected with reasons (the future-you archaeology section)
  and, where relevant, data model / interface sketches.

## Anti-patterns

- **Designing past the spec.** Every element should trace to a criterion.
  "While we're in here, we could also..." is scope creep with a design
  vocabulary.
- **Pro-forma simpler alternative.** Naming a strawman ("we could write it
  in assembly") to dismiss it. The simpler alternative must be one a
  reasonable engineer might actually pick.
- **New dependency by reflex.** A package import is a design decision with
  maintenance cost. The simpler-alternative check applies doubly: can the
  standard library or existing deps do this?
- **Hiding the decision in the implementation.** If stage 6 will face a
  fork (sync vs. async, where state lives, schema shape), decide it here
  on paper — not at the keyboard where momentum decides.
- **Checkpoint theater.** Asking the user to bless a decision with one
  defensible answer. Recommend-and-proceed is the default; the checkpoint
  is for genuine forks.
