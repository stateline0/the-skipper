# Stage 1: Intake & Framing

**Job:** Turn the user's request into a confirmed-or-confirmable problem
statement before any other work happens. This stage is about understanding
the WHAT and WHY — not the how. No solutioning here.

## Process

1. **Restate the goal** in your own words — one to three sentences. What
   problem is being solved, for whom, and why now. If the request is a
   solution ("add a retry loop"), name the underlying problem it implies
   ("requests are failing transiently") — solutions smuggle in assumptions.

2. **List your assumptions explicitly.** Everything you're taking as given
   that the user didn't actually say: which environment, which user flow,
   what stays unchanged, what "done" roughly means. An empty assumptions
   list on a non-trivial task is a red flag — look harder.

3. **Check for competing interpretations.** Could a reasonable person read
   this request two ways? If yes, and the difference changes what gets
   built → checkpoint: present the readings, let the user pick. If the
   difference is cosmetic, pick one, state it as an assumption, move on.

4. **Note what's explicitly OUT.** If the request implies a boundary
   ("just the API, not the UI"), capture it now so later stages don't
   creep across it.

## Output format

```
**Problem:** <restatement>
**Assumptions:**
- <assumption 1>
- <assumption 2>
**Out of scope:** <boundaries, or "none stated">
```

Post this in the conversation, then proceed to stage 2 — unless a
checkpoint condition fired.

## Tier scaling

- **Tier 1:** One sentence + assumptions inline. Example:
  "Fixing the typo in the README install command — assuming you mean the
  `npm` line, not the `pip` one." Then go.
- **Tier 2:** Full output format above, in chat.
- **Tier 3:** Full output format, and it becomes the opening section of a
  persistent doc (e.g., `docs/<feature>/intake.md` or the Linear ticket
  description) that later stages append to.

## Anti-patterns

- **Solutioning during intake.** "I'll add a Redis cache" is stage 4
  content. If an approach is already obvious, hold it — intake locks the
  problem, not the answer.
- **Assumption laundering.** Folding an assumption into the restatement as
  if the user said it. Assumptions go in the list, visibly.
- **Manufactured questions.** If the answer is inferable from the request,
  the codebase, or prior context, it's an assumption to state — not a
  question to ask.
- **Skipping restatement because the request seems obvious.** The
  restatement costs two sentences and is the cheapest misalignment
  detector in the entire chain.
